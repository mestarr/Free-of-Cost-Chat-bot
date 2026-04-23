"""
Free crypto-focused AI chatbot backend.
Uses Groq (free cloud) if GROQ_API_KEY is set; otherwise Ollama (local).
"""
import asyncio
import json
import logging
import os
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .accounts import init_db as init_accounts_db
from .admin_routes import me_router
from .admin_routes import router as admin_router
from .llm_tools import GROQ_TOOLS, execute_tool, normalize_trade_card
from .news import fetch_news_snapshot_for_llm, get_fed_news_api_payload, get_news_api_payload, llm_news_grounding_note
from .observability import RequestLoggingMiddleware, counters_snapshot
from .prices import (
    default_prices_grounding_note,
    fetch_live_price_snapshot,
    fetch_oil_prices_json,
    fetch_prices_json,
    fetch_sparklines_json,
)
from .realtime import router as realtime_router
from .redis_cache import close_client
from .redis_cache import ping as redis_ping
from .saas_middleware import TenantMiddleware

# Load project-root .env (same folder as backend/)
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_root, ".env"))
FRONTEND_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "frontend"))

if not logging.root.handlers:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
# Smaller = faster; larger instruct models (e.g. llama-3.3-70b-versatile on Groq) trade speed for depth.
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
# Automatic fallback when primary model exhausts its daily token quota (TPD).
# Must be a model with its own quota bucket; 8b has the most generous free-tier TPD.
_GROQ_FALLBACK_MODEL = "llama-3.1-8b-instant"
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")
USE_GROQ = bool(GROQ_API_KEY)
# Lower temperature = more grounded, consistent answers for market analysis (override via .env).
_llm_temp_raw = os.getenv("LLM_TEMPERATURE", "0.35").strip()
try:
    LLM_TEMPERATURE = max(0.0, min(2.0, float(_llm_temp_raw)))
except ValueError:
    LLM_TEMPERATURE = 0.35
_llm_max_raw = os.getenv("LLM_MAX_TOKENS", "4096").strip()
try:
    LLM_MAX_TOKENS = max(256, min(32768, int(_llm_max_raw)))
except ValueError:
    LLM_MAX_TOKENS = 4096

_llm_tools_raw = os.getenv("LLM_TOOLS", "1").strip().lower()
LLM_TOOLS_ENABLED = _llm_tools_raw not in ("0", "false", "no", "off")
_llm_tool_rounds_raw = os.getenv("LLM_MAX_TOOL_ROUNDS", "8").strip()
try:
    LLM_MAX_TOOL_ROUNDS = max(1, min(16, int(_llm_tool_rounds_raw)))
except ValueError:
    LLM_MAX_TOOL_ROUNDS = 8

# Groq free/on-demand tiers often cap a single request at ~6000 tokens (prompt + max_tokens + tool schemas).
# Default completion cap stays well below LLM_MAX_TOKENS so prompt + requested output fits.
_groq_cap_raw = os.getenv("GROQ_MAX_COMPLETION_TOKENS", "2048").strip()
try:
    GROQ_MAX_COMPLETION_TOKENS = max(256, min(8192, int(_groq_cap_raw)))
except ValueError:
    GROQ_MAX_COMPLETION_TOKENS = 2048
_groq_req_raw = os.getenv("GROQ_PER_REQUEST_TOKEN_LIMIT", "6000").strip()
try:
    GROQ_PER_REQUEST_TOKEN_LIMIT = max(1024, min(200_000, int(_groq_req_raw)))
except ValueError:
    GROQ_PER_REQUEST_TOKEN_LIMIT = 6000
_groq_tool_cap_raw = os.getenv("GROQ_MAX_TOOL_RESPONSE_CHARS", "9000").strip()
try:
    GROQ_MAX_TOOL_RESPONSE_CHARS = max(2000, min(100_000, int(_groq_tool_cap_raw)))
except ValueError:
    GROQ_MAX_TOOL_RESPONSE_CHARS = 9000
_groq_hist_raw = os.getenv("GROQ_MAX_CHAT_MESSAGES", "4").strip()
try:
    GROQ_MAX_CHAT_MESSAGES = max(2, min(48, int(_groq_hist_raw)))
except ValueError:
    GROQ_MAX_CHAT_MESSAGES = 4
_groq_asst_raw = os.getenv("GROQ_MAX_ASSISTANT_CHARS", "3500").strip()
try:
    GROQ_MAX_ASSISTANT_CHARS = max(800, min(50_000, int(_groq_asst_raw)))
except ValueError:
    GROQ_MAX_ASSISTANT_CHARS = 3500

_GROQ_TOOLS_JSON_LEN: int | None = None

SYSTEM_PROMPT = """You are Crypto ChatPal, a direct crypto market analyst. Be clear, specific, and practical. No fluff.

Core behavior:
- Format-first (overrides default trade verbosity): ONLY applies when the user EXPLICITLY includes a format constraint in that message — e.g. "answer yes or no", "one word only", "just A or B", "single sentence only", "no essay". It does NOT apply just because the question CAN be answered with yes/no. "Should I buy BTC?", "Do I need to buy now?", "Is it a good time to sell?" are TRADE ACTION questions — they ALWAYS get the full decision framework (scorecard + plan), even though they could technically be answered with yes or no.
- When format-first does apply: use plain text only; do not call emit_trade_analysis; do not use the scorecard template for that turn. For strict "yes or no", start with exactly "Yes" or "No"; you may add at most one short parenthetical (≤8 words) only if needed for honesty, e.g. "No (wait — weak setup)".
- Format-first resets on follow-up: if the very next user message is a clarification or elaboration request (e.g. "what do you mean?", "explain that", "why?", "elaborate", "tell me more"), treat it as a normal open-ended question — give a full explanation. The format constraint from the previous turn does NOT carry over.
- Match response shape to intent:
  - Education, definitions, how things work, history, or general discussion: answer directly in plain language. Do not use the full trade scorecard / entry-exit plan unless the user clearly asks for trading or investment action.
  - Trading or investment action (buy/sell/hold, entries, targets, sizing, "what should I do", "do I need to buy", "should I buy/sell", portfolio moves): use the full decision framework and structured format below — except when an explicit format-first rule applies.
  - Timing and follow-up questions ("how long should I wait?", "when to buy?", "how much longer?"): give a specific, reasoned answer using available price/news context. State key conditions that would change the timing (e.g. "wait for X level", "watch for Y event"). Never say "no timeframe in context" and stop — use what IS available (live price, trend, news) to give a practical estimate.
- You ARE allowed to give a directional trading opinion when asked (buy / sell / hold), but present it as probabilistic analysis, never certainty.
- Follow Grounding rules (below) for every factual claim about live markets, current prices, or news in this session.
- If injected data is missing or stale, say so explicitly and lower confidence; never fill gaps with invented numbers or headlines.
- Use only available evidence: user messages, attached files, injected system blocks (live prices, headlines, grounding notes), and tool results you receive in this turn. Treat those as authoritative for numbers and headlines; do not invent prices, dates, or stories.
- Respond in the same language as the user unless they ask otherwise.

Tools (when the API exposes them to you):
- You may call tools to fetch CoinGecko USD prices, pull more crypto RSS headlines, or load a macro bundle (oil/metals + Fed-tagged headlines). Use tools when the user needs assets or stories beyond the initial injected blocks, or asks for refreshed/specialized data.
- For trading or investment action (buy/sell/hold, sizing, plan, scorecard), call emit_trade_analysis once with structured fields, then still write a clear natural-language answer — unless the user message is only a format constraint (yes/no, one word, etc.); then skip tools and emit_trade_analysis entirely.

Grounding rules (strict — read before answering):
- What counts as "in context" for live/session-specific claims:
  1) Injected system messages in this request: optional grounding manifest (what is attached + freshness), optional USD spot snapshot (CoinGecko, default watchlist only), optional RSS headline list (each line: source, title, snippet, URL).
  2) The user's messages, including any pasted or attached file text they sent in this chat.
  3) Tool JSON you receive in this same request after calling get_prices, get_crypto_headlines, or get_macro_snapshot.
- General crypto education (definitions, how protocols work, historical patterns as concepts) may use broad knowledge, but you must not present it as today's live price or a real headline unless that exact fact appears in (1)–(3). When mixing, label briefly: e.g. "From the price snapshot:" / "From headlines:" / "General concept (not from live feed):".
- Forbidden: fabricating USD prices, 24h % moves, dates/times of news, headline wording, outlet names, article URLs, or "the data shows X" when X is not in (1)–(3). Do not imply you saw the full article body unless the user pasted it.
- Asset scope: the spot block only covers coins listed in that snapshot. If the user asks about another asset, say it is outside the injected watchlist unless they supplied a price in chat; do not guess a spot price.
- Headlines: only discuss stories from the injected headline block or from get_crypto_headlines tool output; attribute with source and use the provided link when pointing to a story. Do not invent related stories.
- Staleness: the manifest and context-anchor time describe recency. If data may be outdated for a fast market, say that and soften time-sensitive claims.
- Contradictions: if user text conflicts with an injected snapshot, call it out and prefer the snapshot for numbers unless the user clearly gives a newer figure as their own input.

Required decision framework for trade-opinion questions:
1) Thesis (1-2 lines): what side and why.
2) Scorecard (0-100):
   - Trend / momentum (0-25)
   - News / macro impact (0-25)
   - Risk-reward quality (0-25)
   - Market risk regime / volatility (0-25)
   Final score = sum.
3) Action label:
   - 70-100: Buy bias
   - 55-69: Lean buy / Hold
   - 45-54: Neutral / Wait
   - 30-44: Lean sell / Reduce
   - 0-29: Sell bias
4) Trade plan (if user asks for execution):
   - Entry zone (or "wait for confirmation")
   - Invalidation level (where thesis is wrong)
   - 2 take-profit levels
   - Position sizing: default risk per trade 0.5-1.0% of total capital
   - R:R must be >= 1.8, otherwise advise no-trade
5) Risk controls:
   - Mention key downside risks (at least 2)
   - Mention correlation/macro risk when relevant (rates, USD, oil, risk-off)
6) Confidence:
   - Provide confidence 0-100 with one-line reason.

Output format for buy/sell questions:
- View: <Buy bias / Sell bias / Hold>
- Confidence: <0-100>%
- Score: <0-100> (Trend X + News/Macro X + R:R X + Regime X)
- Why: 3-5 concise bullets
- Plan: entry / invalidation / TP1 / TP2
- Risk note: one short paragraph

General safety and quality:
- Do not ask for passwords, private keys, or seed phrases.
- If user asks for illegal manipulation, scams, or fraud, refuse.
- Be honest about uncertainty.
- This is analysis support, not guaranteed outcome.

Decision quality upgrades (mandatory):
- First identify intent: spot swing trade, intraday trade, or long-term investing.
- If timeframe/risk profile is missing, assume "swing (days-weeks), balanced risk" and state the assumption.
- Always run a no-trade filter. Recommend "No trade / Wait" if any condition fails:
  1) R:R < 1.8
  2) Invalidation is unclear
  3) News flow is contradictory with weak trend
  4) Volatility/regime is unstable and confidence < 55
- Prefer capital protection over activity. Missing a trade is better than forcing a bad one.
- Never use all-in language. Position sizing must stay small and risk-defined.

Technical checklist (use what is available; do not invent values):
- Trend context: higher highs/higher lows or the opposite.
- Momentum confirmation: acceleration/deceleration behavior.
- Key levels: support/resistance or breakdown/breakout zones.
- Asymmetry: downside vs upside distance to invalidation/targets.

Macro/news checklist:
- Mention whether current news is supportive, neutral, or adverse for the asset.
- Mention at least one macro cross-current when relevant (Fed policy, USD, yields, oil, risk-on/off).
- If major event risk is near (FOMC/CPI-like), reduce confidence and position size guidance.

Response discipline:
- If confidence < 60, default to Hold/Wait unless user explicitly asks for aggressive mode.
- Include one "What changes my view" bullet (skip if the user forbade extra content, e.g. strict yes/no only).
- Keep answers short, structured, and numeric where possible.
- If the user demanded a minimal format, do not open with grounding-manifest recap or a trade card; deliver the constrained answer first.
- A follow-up message that asks for clarification or explanation ("what do you mean", "why", "explain", "elaborate") is never a format constraint — always give a full, helpful answer for that message.

Smarter reasoning (internal; keep the reply concise):
1) Classify: trade action vs education vs news vs portfolio vs format-only (yes/no, one word) — lead with what they asked; honor format-only before any tool or scorecard.
2) Apply Grounding rules: every number (price, %, date, metric) must trace to user text, attachments, injected blocks, or tool output; otherwise say it is not in context and do not guess.
3) If prices and headlines conflict, state the tension and lower confidence instead of forcing one narrative.
4) Ask at most one clarifying question when it would materially change the answer; else state one-line assumptions.
5) Before a strong view, check it still holds using only available data; if not, soften or recommend wait.
6) Multi-part questions: answer each part with a short header or number.

Quality bar:
- Prefer one precise paragraph over vague lists when the user asks "why" or "explain".
- Distinguish facts (from context) vs inference vs opinion — label when it matters.
- If the user is wrong about a fact present in context, correct gently with the sourced value.
"""


class ChatMessage(BaseModel):
    role: str
    content: str = Field(max_length=200_000)


class ChatRequest(BaseModel):
    messages: list[ChatMessage]


class ChatResponse(BaseModel):
    message: str
    model: str
    trade: dict | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_accounts_db()
    if USE_GROQ:
        print("Using Groq (free cloud). No Ollama needed.")
        if LLM_TOOLS_ENABLED:
            print("Groq tool calling enabled (set LLM_TOOLS=0 in .env to disable).")
    else:
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(f"{OLLAMA_URL}/api/tags", timeout=2.0)
                if r.status_code != 200:
                    print("Warning: Ollama returned non-200. Is a model pulled? Run: ollama pull llama3.2")
        except Exception as e:
            print(f"Ollama not reachable. Set GROQ_API_KEY to use Groq instead, or start Ollama and run 'ollama pull {OLLAMA_MODEL}'.\n{e}")
    yield
    await close_client()


app = FastAPI(title="Crypto ChatPal", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(TenantMiddleware)
app.include_router(admin_router)
app.include_router(me_router)
app.include_router(realtime_router)


@app.get("/api/health")
async def api_health():
    """Liveness: process up; optional Redis ping when REDIS_URL is set."""
    out: dict = {
        "ok": True,
        "auth_mode": os.getenv("CCP_AUTH_MODE", "off").strip().lower(),
        "redis_cache": bool(os.getenv("REDIS_URL", "").strip()),
    }
    if os.getenv("REDIS_URL", "").strip():
        out["redis"] = await redis_ping()
    else:
        out["redis"] = None
    return out


@app.get("/api/metrics")
async def api_metrics(response_format: str | None = Query(None, alias="format")):
    """In-process counters and average HTTP latency (Prometheus text if format=prometheus)."""
    c = counters_snapshot()
    n = max(1, c.get("http_requests", 0))
    avg = c.get("http_latency_ms_sum", 0) / n
    if response_format == "prometheus":
        lines = [
            "# HELP ccp_http_requests_total HTTP requests counted by middleware",
            "# TYPE ccp_http_requests_total counter",
            f"ccp_http_requests_total {c.get('http_requests', 0)}",
            "# HELP ccp_http_errors_total Responses with status >= 500 (and uncaught exceptions)",
            "# TYPE ccp_http_errors_total counter",
            f"ccp_http_errors_total {c.get('http_errors', 0)}",
            "# HELP ccp_price_cache_hit_total Price cache hits (memory or Redis)",
            "# TYPE ccp_price_cache_hit_total counter",
            f"ccp_price_cache_hit_total {c.get('price_cache_hit', 0)}",
            "# HELP ccp_price_cache_miss_total Price cache misses (upstream fetch)",
            "# TYPE ccp_price_cache_miss_total counter",
            f"ccp_price_cache_miss_total {c.get('price_cache_miss', 0)}",
            "# HELP ccp_news_cache_hit_total News cache hits",
            "# TYPE ccp_news_cache_hit_total counter",
            f"ccp_news_cache_hit_total {c.get('news_cache_hit', 0)}",
            "# HELP ccp_news_cache_miss_total News cache misses",
            "# TYPE ccp_news_cache_miss_total counter",
            f"ccp_news_cache_miss_total {c.get('news_cache_miss', 0)}",
            "# HELP ccp_http_latency_avg_ms Average request latency (ms)",
            "# TYPE ccp_http_latency_avg_ms gauge",
            f"ccp_http_latency_avg_ms {round(avg, 4)}",
        ]
        return Response("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")
    return {"counters": c, "http_latency_avg_ms": round(avg, 2)}


_GROQ_SHORT_USER_HINTS = (
    "yes or no",
    "no or yes",
    "one word",
    "y/n",
    "only yes",
    "only no",
    "answer with yes",
    "answer with no",
    "single sentence",
    "just yes",
    "just no",
    "binary answer",
    "a or b only",
)


def _last_user_content_from_request(req: ChatRequest) -> str:
    for m in reversed(req.messages):
        if m.role == "user":
            return (m.content or "").strip()
    return ""


def _groq_last_user_text(messages: list[dict]) -> str:
    for m in reversed(messages):
        if m.get("role") == "user" and isinstance(m.get("content"), str):
            return m["content"].strip()
    return ""


def _groq_short_format_turn(user_text: str) -> bool:
    """Short / format-only user line: omit RSS injection + tools to cut tokens (TPD/TPM)."""
    u = user_text.strip().lower()
    if len(u) > 220:
        return False
    if any(h in u for h in _GROQ_SHORT_USER_HINTS):
        return True
    compact = u.rstrip("?.!").strip()
    if len(compact) <= 28 and compact in ("yes", "no", "ok", "why", "please", "thanks", "answer", "answer me"):
        return True
    return False


def _build_messages(
    req: ChatRequest,
    price_snapshot: str = "",
    news_snapshot: str = "",
    price_grounding: str = "",
    news_grounding: str = "",
    omit_rss_block: bool = False,
) -> list[dict]:
    """System prompt + grounding manifest + optional live prices + headlines + conversation history."""
    utc_now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    out: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "system",
            "content": f"Context anchor: server time is {utc_now}. Use this for recency; injected prices/news may be slightly older than this instant.",
        },
    ]
    pg = (price_grounding or "").strip() or "Price feed: status unknown."
    ng = (news_grounding or "").strip() or "News feed: status unknown."
    manifest_lines = [
        "Grounding manifest (what is attached this request — obey Grounding rules in the main system prompt):",
        pg,
        ng,
    ]
    if price_snapshot.strip():
        manifest_lines.append("Following message: USD spot snapshot (authoritative for listed assets only).")
    else:
        manifest_lines.append("No USD spot snapshot message follows.")
    news_body = "" if omit_rss_block else (news_snapshot or "").strip()
    if news_body:
        manifest_lines.append("Following message: RSS headline list (authoritative for those stories only).")
    elif omit_rss_block:
        manifest_lines.append(
            "RSS headline list omitted this turn (short / format-only request) to save API tokens; "
            "use earlier turns if headlines were discussed."
        )
    else:
        manifest_lines.append("No RSS headline list message follows.")
    out.append({"role": "system", "content": "\n".join(manifest_lines)})
    if price_snapshot:
        out.append({"role": "system", "content": price_snapshot})
    if news_body:
        out.append({"role": "system", "content": news_body})
    for m in req.messages:
        out.append({"role": m.role, "content": m.content})
    return out


def _apply_groq_history_cap(messages: list[dict]) -> list[dict]:
    """Keep all leading system blocks; drop oldest user/assistant/tool tail items over cap (saves TPM)."""
    split = 0
    while split < len(messages) and messages[split].get("role") == "system":
        split += 1
    head = messages[:split]
    tail = messages[split:]
    if len(tail) <= GROQ_MAX_CHAT_MESSAGES:
        return [dict(m) for m in messages]
    kept = tail[-GROQ_MAX_CHAT_MESSAGES :]
    while kept and kept[0].get("role") == "tool":
        kept = kept[1:]
    return [dict(m) for m in head + kept]


def _compress_assistant_turns_for_groq(messages: list[dict]) -> list[dict]:
    """Shorten past assistant text (long trade writeups) while keeping the tail."""
    out: list[dict] = []
    for m in messages:
        mc = dict(m)
        if mc.get("role") == "assistant" and isinstance(mc.get("content"), str):
            c = mc["content"]
            cap = GROQ_MAX_ASSISTANT_CHARS
            if len(c) > cap:
                keep = cap - 80
                mc["content"] = "[…earlier assistant text truncated for rate limits…]\n" + c[-keep:]
        out.append(mc)
    return out


def _groq_tools_overhead_tokens() -> int:
    global _GROQ_TOOLS_JSON_LEN
    if _GROQ_TOOLS_JSON_LEN is None:
        _GROQ_TOOLS_JSON_LEN = len(json.dumps(GROQ_TOOLS))
    return max(350, _GROQ_TOOLS_JSON_LEN // 3)


def _groq_max_output_tokens() -> int:
    return max(64, min(LLM_MAX_TOKENS, GROQ_MAX_COMPLETION_TOKENS))


def _groq_completion_cap(low_token: bool) -> int:
    base = _groq_max_output_tokens()
    if low_token:
        return max(64, min(base, 384))
    return base


def _groq_estimated_prompt_token_budget() -> int:
    out = _groq_max_output_tokens()
    tools = _groq_tools_overhead_tokens() if LLM_TOOLS_ENABLED else 0
    return max(600, GROQ_PER_REQUEST_TOKEN_LIMIT - out - tools - 300)


def _rough_token_estimate(text: str | None) -> int:
    if not text:
        return 0
    return max(1, len(text) // 4)


def _messages_estimated_prompt_tokens(messages: list[dict]) -> int:
    n = 0
    for m in messages:
        c = m.get("content")
        if isinstance(c, str):
            n += _rough_token_estimate(c)
        elif c is not None:
            n += _rough_token_estimate(json.dumps(c))
        tc = m.get("tool_calls")
        if tc:
            n += _rough_token_estimate(json.dumps(tc))
    return n


def _trim_messages_for_groq(messages: list[dict]) -> list[dict]:
    """Shrink prompt to fit Groq per-request limits (drops old turns, then truncates text)."""
    budget = _groq_estimated_prompt_token_budget()
    out = [dict(m) for m in messages]

    def est() -> int:
        return _messages_estimated_prompt_tokens(out)

    iterations = 0
    while est() > budget and iterations < 250:
        iterations += 1
        i0 = 0
        while i0 < len(out) and out[i0].get("role") == "system":
            i0 += 1
        if i0 < len(out) and len(out) - i0 > 1:
            out.pop(i0)
            continue
        if i0 < len(out):
            last = out[-1]
            c = last.get("content")
            if isinstance(c, str) and len(c) > 500:
                over = est() - budget
                chop = min(len(c) - 300, max(over * 4 + 200, 300))
                if chop > 0:
                    last["content"] = f"[…{chop} characters omitted…]\n" + c[chop:]
                    continue
        longest_j = -1
        longest_len = 0
        for j, m in enumerate(out):
            if m.get("role") != "system":
                continue
            sc = m.get("content")
            if isinstance(sc, str) and len(sc) > longest_len:
                longest_len = len(sc)
                longest_j = j
        if longest_j >= 0 and longest_len > 800:
            sc = out[longest_j]["content"]
            over = est() - budget
            newlen = max(400, longest_len - max(over * 4 + 100, 200))
            if newlen < longest_len:
                out[longest_j]["content"] = sc[:newlen] + "\n[… truncated for token limit …]"
                continue
        break
    return out


def _cap_tool_message_content(text: str) -> str:
    if len(text) <= GROQ_MAX_TOOL_RESPONSE_CHARS:
        return text
    return text[: GROQ_MAX_TOOL_RESPONSE_CHARS - 80] + "\n...[tool output truncated for Groq size limit]"


def _groq_api_error_detail(response: httpx.Response) -> str:
    raw = response.text or ""
    detail = raw
    try:
        err_j = response.json()
        em = err_j.get("error")
        if isinstance(em, dict):
            detail = str(em.get("message") or raw)
        elif isinstance(em, str):
            detail = em
    except (json.JSONDecodeError, ValueError, TypeError):
        pass
    dlow = detail.lower()
    if "tokens per day" in dlow:
        detail += (
            " | TPD: daily token cap hit. Use GROQ_MODEL=llama-3.1-8b-instant, LLM_TOOLS=0, "
            "start a new chat, shorten threads (GROQ_MAX_CHAT_MESSAGES), or wait for the reset window."
        )
    elif "tpm" in dlow or "too large" in dlow or "reduce your message" in dlow:
        detail += (
            " | Tip: lower GROQ_MAX_COMPLETION_TOKENS, set GROQ_MAX_CHAT_MESSAGES=4, "
            "GROQ_MAX_ASSISTANT_CHARS=2500, or NEWS_MAX_HEADLINES_LLM=8 in .env."
        )
    return detail


def _ollama_options() -> dict:
    return {"temperature": LLM_TEMPERATURE, "num_predict": LLM_MAX_TOKENS}


def _groq_retry_after_seconds(response: httpx.Response) -> float | None:
    ra = response.headers.get("retry-after")
    if ra:
        try:
            return min(float(ra), 120.0)
        except ValueError:
            pass
    text = response.text or ""
    m = re.search(r"try again in ([\d.]+)\s*s", text, re.I)
    if m:
        return min(float(m.group(1)) + 0.35, 120.0)
    return None


def _groq_is_daily_quota_429(response: httpx.Response) -> bool:
    """Daily TPD limits need a long wait — do not burn retries like TPM bursts."""
    if response.status_code != 429:
        return False
    t = (response.text or "").lower()
    return "tokens per day" in t


async def _groq_post_chat_completion(client: httpx.AsyncClient, payload: dict) -> httpx.Response:
    """POST chat completions; on 429 / TPM wait and retry with backoff (not for TPD daily cap)."""
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    max_attempts = 6
    backoff = 2.0
    last: httpx.Response | None = None
    for _attempt in range(max_attempts):
        r = await client.post(url, headers=headers, json=payload)
        last = r
        if r.status_code != 429:
            return r
        if _groq_is_daily_quota_429(r):
            return r
        wait = _groq_retry_after_seconds(r)
        if wait is None:
            wait = backoff
        wait = min(max(wait, 1.5), 90.0)
        await asyncio.sleep(wait)
        backoff = min(backoff * 1.75, 45.0)
    return last  # type: ignore[return-value]


async def _groq_complete_multistep(client: httpx.AsyncClient, messages: list[dict]) -> tuple[str, str, dict | None]:
    """Groq chat with optional tool loop; returns (assistant text, model id, optional trade dict from emit_trade_analysis)."""
    msgs: list[dict] = _compress_assistant_turns_for_groq(_apply_groq_history_cap([dict(x) for x in messages]))
    low = _groq_short_format_turn(_groq_last_user_text(msgs))
    trade_card: dict | None = None
    model_out = GROQ_MODEL
    max_rounds = 1 if (low or not LLM_TOOLS_ENABLED) else LLM_MAX_TOOL_ROUNDS

    active_model = GROQ_MODEL
    for _ in range(max_rounds):
        msgs = _trim_messages_for_groq(msgs)
        payload: dict = {
            "model": active_model,
            "messages": msgs,
            "temperature": LLM_TEMPERATURE,
            "max_tokens": _groq_completion_cap(low),
        }
        if LLM_TOOLS_ENABLED and not low:
            payload["tools"] = GROQ_TOOLS
            payload["tool_choice"] = "auto"

        r = await _groq_post_chat_completion(client, payload)

        # TPD daily cap: if primary model quota exhausted, fall back to 8b automatically
        if r.status_code == 429 and _groq_is_daily_quota_429(r) and active_model != _GROQ_FALLBACK_MODEL:
            active_model = _GROQ_FALLBACK_MODEL
            fallback_payload: dict = {
                "model": active_model,
                "messages": msgs,
                "temperature": LLM_TEMPERATURE,
                "max_tokens": min(_groq_completion_cap(low), 1024),
            }
            r = await _groq_post_chat_completion(client, fallback_payload)

        r.raise_for_status()
        data = r.json()
        choice0 = (data.get("choices") or [{}])[0]
        model_out = data.get("model") or active_model
        msg = choice0.get("message") or {}
        finish_reason = choice0.get("finish_reason") or ""

        # failed_generation: model produced a malformed tool call — strip tools and get a plain answer
        if finish_reason == "failed_generation":
            plain_payload2: dict = {
                "model": active_model,
                "messages": msgs,
                "temperature": LLM_TEMPERATURE,
                "max_tokens": min(_groq_completion_cap(low), 1024),
            }
            r2 = await _groq_post_chat_completion(client, plain_payload2)
            r2.raise_for_status()
            data2 = r2.json()
            c2 = ((data2.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
            return (c2.strip() or "I could not generate a response — try rephrasing your question."), model_out, trade_card

        tcalls = msg.get("tool_calls")

        if tcalls:
            if not LLM_TOOLS_ENABLED:
                return (
                    "Tools are disabled on the server; answer using only injected context.",
                    model_out,
                    trade_card,
                )
            assistant_msg: dict = {"role": "assistant", "content": msg.get("content"), "tool_calls": tcalls}
            msgs.append(assistant_msg)
            for tc in tcalls:
                if not isinstance(tc, dict):
                    continue
                fn = tc.get("function") or {}
                name = (fn.get("name") or "").strip()
                args = fn.get("arguments")
                if not isinstance(args, str):
                    args = json.dumps(args) if args is not None else "{}"
                tid = tc.get("id") or ""
                if name == "emit_trade_analysis":
                    try:
                        parsed = json.loads(args)
                        if isinstance(parsed, dict):
                            trade_card = normalize_trade_card(parsed)
                    except json.JSONDecodeError:
                        pass
                tool_text = _cap_tool_message_content(await execute_tool(name, args))
                msgs.append({"role": "tool", "tool_call_id": tid, "content": tool_text})
            continue

        content = (msg.get("content") or "").strip()
        return content, model_out, trade_card

    # Model kept requesting tools until round cap — one final completion without tools so the user
    # still gets an answer (broad questions like "crypto world situation" can burn many tool rounds).
    msgs = _trim_messages_for_groq(msgs)
    fallback_tail = [
        {
            "role": "user",
            "content": (
                "You used many tool rounds. Now write the full answer for the user in natural language only. "
                "Use the injected context and any tool JSON already in this thread; do not call tools again."
            ),
        }
    ]
    payload_final: dict = {
        "model": active_model,
        "messages": msgs + fallback_tail,
        "temperature": LLM_TEMPERATURE,
        "max_tokens": _groq_completion_cap(low),
    }
    r = await _groq_post_chat_completion(client, payload_final)
    if r.status_code == 429 and _groq_is_daily_quota_429(r) and active_model != _GROQ_FALLBACK_MODEL:
        active_model = _GROQ_FALLBACK_MODEL
        payload_final["model"] = active_model
        payload_final["max_tokens"] = min(payload_final["max_tokens"], 1024)
        r = await _groq_post_chat_completion(client, payload_final)
    r.raise_for_status()
    data = r.json()
    choice0 = (data.get("choices") or [{}])[0]
    model_out = data.get("model") or active_model
    msg = choice0.get("message") or {}
    content = (msg.get("content") or "").strip()
    if not content:
        return (
            "I pulled live data but ran out of model steps before a final reply. "
            "Try again, or ask one focused question (e.g. a single coin or topic).",
            model_out,
            trade_card,
        )
    return content, model_out, trade_card


@app.get("/api/prices")
async def api_prices(
    ids: str | None = Query(
        None,
        max_length=2048,
        description="Comma-separated CoinGecko coin ids (optional). Omit for default set.",
    ),
):
    """Live USD spot prices (CoinGecko). Pass `ids` to match the UI watchlist."""
    try:
        return await fetch_prices_json(ids_csv=ids)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Price feed unavailable: {e!s}") from e


@app.get("/api/prices/sparklines")
async def api_prices_sparklines(
    ids: str | None = Query(
        None,
        max_length=2048,
        description="Comma-separated CoinGecko coin ids. Omit for default watchlist.",
    ),
):
    """24h price series per coin (hourly, downsampled). Cached separately from spot."""
    try:
        return await fetch_sparklines_json(ids_csv=ids)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Sparkline feed unavailable: {e!s}") from e


@app.get("/api/news")
async def api_news():
    """Headlines from RSS (CoinDesk, Decrypt, BeInCrypto)."""
    try:
        return await get_news_api_payload()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"News feed unavailable: {e!s}") from e


@app.get("/api/news/fed")
async def api_news_fed():
    """Latest Federal Reserve Board news (press + speeches via RSS)."""
    try:
        return await get_fed_news_api_payload()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Federal Reserve news unavailable: {e!s}") from e


@app.get("/api/markets/oil")
async def api_markets_oil():
    """WTI/Brent plus Gold/Silver delayed benchmark quotes."""
    try:
        return await fetch_oil_prices_json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Oil market feed unavailable: {e!s}") from e


@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """Send conversation to Groq or Ollama with crypto-focused system prompt."""
    snapshot = await fetch_live_price_snapshot()
    lu = _last_user_content_from_request(req)
    omit_rss = USE_GROQ and _groq_short_format_turn(lu)
    news_snap = "" if omit_rss else await fetch_news_snapshot_for_llm()
    messages = _build_messages(
        req,
        snapshot,
        news_snap,
        default_prices_grounding_note(),
        llm_news_grounding_note(),
        omit_rss_block=omit_rss,
    )

    if USE_GROQ:
        async with httpx.AsyncClient(timeout=120.0) as client:
            try:
                content, model_used, trade = await _groq_complete_multistep(client, messages)
                return ChatResponse(message=content, model=model_used, trade=trade)
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 401:
                    detail = "Invalid GROQ_API_KEY. Get a free key at https://console.groq.com"
                else:
                    detail = _groq_api_error_detail(e.response)
                raise HTTPException(status_code=e.response.status_code, detail=detail)
    else:
        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                r = await client.post(
                    f"{OLLAMA_URL}/api/chat",
                    json={
                        "model": OLLAMA_MODEL,
                        "messages": messages,
                        "stream": False,
                        "options": _ollama_options(),
                    },
                )
                r.raise_for_status()
                data = r.json()
                message = data.get("message", {})
                content = message.get("content", "").strip()
                return ChatResponse(message=content, model=data.get("model", OLLAMA_MODEL))
            except httpx.ConnectError:
                raise HTTPException(
                    status_code=503,
                    detail="Ollama not running. Install from https://ollama.com or set GROQ_API_KEY for free cloud (https://console.groq.com).",
                )
            except httpx.HTTPStatusError as e:
                raise HTTPException(status_code=e.response.status_code, detail=e.response.text)


def _ndjson_line(obj: dict) -> bytes:
    return (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")


async def _stream_chat_ndjson(messages: list[dict]) -> AsyncIterator[bytes]:
    """Yield NDJSON lines: {"c":"chunk"} text deltas, then {"done":true,"model":...} or {"error":"..."}."""
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            if USE_GROQ:
                try:
                    content, model_used, trade = await _groq_complete_multistep(client, messages)
                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 401:
                        detail = "Invalid GROQ_API_KEY. Get a free key at https://console.groq.com"
                    else:
                        detail = _groq_api_error_detail(e.response)
                    yield _ndjson_line({"error": detail})
                    return
                except Exception as e:
                    yield _ndjson_line({"error": str(e)})
                    return
                if trade:
                    yield _ndjson_line({"trade": trade})
                chunk_size = 48
                if not content:
                    yield _ndjson_line({"c": "(No text returned.)"})
                else:
                    for i in range(0, len(content), chunk_size):
                        yield _ndjson_line({"c": content[i : i + chunk_size]})
                yield _ndjson_line({"done": True, "model": model_used, "trade": trade})
            else:
                model_out = OLLAMA_MODEL
                async with client.stream(
                    "POST",
                    f"{OLLAMA_URL}/api/chat",
                    json={
                        "model": OLLAMA_MODEL,
                        "messages": messages,
                        "stream": True,
                        "options": _ollama_options(),
                    },
                ) as r:
                    if r.status_code != 200:
                        raw = (await r.aread()).decode(errors="replace")
                        yield _ndjson_line({"error": raw or r.reason_phrase})
                        return
                    async for line in r.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            obj = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if obj.get("done"):
                            model_out = obj.get("model") or OLLAMA_MODEL
                            break
                        piece = (obj.get("message") or {}).get("content") or ""
                        if piece:
                            yield _ndjson_line({"c": piece})
                    yield _ndjson_line({"done": True, "model": model_out})
    except httpx.ConnectError:
        yield _ndjson_line(
            {
                "error": "Ollama not running. Install from https://ollama.com or set GROQ_API_KEY for free cloud (https://console.groq.com).",
            }
        )
    except Exception as e:
        yield _ndjson_line({"error": str(e)})


@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest):
    """Same context as /api/chat but streams assistant text as NDJSON (one JSON object per line)."""
    snapshot = await fetch_live_price_snapshot()
    lu = _last_user_content_from_request(req)
    omit_rss = USE_GROQ and _groq_short_format_turn(lu)
    news_snap = "" if omit_rss else await fetch_news_snapshot_for_llm()
    messages = _build_messages(
        req,
        snapshot,
        news_snap,
        default_prices_grounding_note(),
        llm_news_grounding_note(),
        omit_rss_block=omit_rss,
    )

    return StreamingResponse(
        _stream_chat_ndjson(messages),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# Serve frontend (explicit favicon so GET /favicon.ico is not 404 before static mount)
@app.get("/favicon.ico", include_in_schema=False)
async def favicon_ico():
    path = os.path.join(FRONTEND_DIR, "favicon.svg")
    if os.path.isfile(path):
        return FileResponse(
            path,
            media_type="image/svg+xml",
            headers={"Cache-Control": "public, max-age=86400"},
        )
    raise HTTPException(status_code=404, detail="favicon missing")


if os.path.isdir(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="static")
