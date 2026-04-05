"""
Free crypto-focused AI chatbot backend.
Uses Groq (free cloud) if GROQ_API_KEY is set; otherwise Ollama (local).
"""
import json
import os
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from contextlib import asynccontextmanager

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .news import fetch_news_snapshot_for_llm, get_fed_news_api_payload, get_news_api_payload, llm_news_grounding_note
from .prices import (
    default_prices_grounding_note,
    fetch_live_price_snapshot,
    fetch_oil_prices_json,
    fetch_prices_json,
)

# Load project-root .env (same folder as backend/)
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_root, ".env"))
FRONTEND_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "frontend"))

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
# Smaller = faster; larger instruct models (e.g. llama-3.3-70b-versatile on Groq) trade speed for depth.
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
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

SYSTEM_PROMPT = """You are Crypto ChatPal, a direct crypto market analyst. Be clear, specific, and practical. No fluff.

Core behavior:
- Match response shape to intent:
  - Education, definitions, how things work, history, or general discussion: answer directly in plain language. Do not use the full trade scorecard / entry-exit plan unless the user clearly asks for trading or investment action.
  - Trading or investment action (buy/sell/hold, entries, targets, sizing, "what should I do", portfolio moves): use the full decision framework and structured format below.
- You ARE allowed to give a directional trading opinion when asked (buy / sell / hold), but present it as probabilistic analysis, never certainty.
- Follow Grounding rules (below) for every factual claim about live markets, current prices, or news in this session.
- If injected data is missing or stale, say so explicitly and lower confidence; never fill gaps with invented numbers or headlines.
- Use only available evidence: user messages, attached files, and the injected system blocks (live prices, headlines, grounding notes). Treat those blocks as the only authoritative numbers and story list; do not invent prices, dates, or headlines.
- If data is missing or stale, explicitly say so and lower confidence.
- Respond in the same language as the user unless they ask otherwise.

Grounding rules (strict — read before answering):
- What counts as "in context" for live/session-specific claims:
  1) Injected system messages in this request: optional grounding manifest (what is attached + freshness), optional USD spot snapshot (CoinGecko, default watchlist only), optional RSS headline list (each line: source, title, snippet, URL).
  2) The user's messages, including any pasted or attached file text they sent in this chat.
- General crypto education (definitions, how protocols work, historical patterns as concepts) may use broad knowledge, but you must not present it as today's live price or a real headline unless that exact fact appears in (1) or (2). When mixing, label briefly: e.g. "From the price snapshot:" / "From headlines:" / "General concept (not from live feed):".
- Forbidden: fabricating USD prices, 24h % moves, dates/times of news, headline wording, outlet names, article URLs, or "the data shows X" when X is not in (1)–(2). Do not imply you saw the full article body unless the user pasted it.
- Asset scope: the spot block only covers coins listed in that snapshot. If the user asks about another asset, say it is outside the injected watchlist unless they supplied a price in chat; do not guess a spot price.
- Headlines: only discuss stories that appear in the headline block; attribute with source and use the provided link when pointing to a story. Do not invent related stories.
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
- Include one "What changes my view" bullet.
- Keep answers short, structured, and numeric where possible.

Smarter reasoning (internal; keep the reply concise):
1) Parse the ask: trade idea vs education vs news vs portfolio — answer that shape first.
2) Apply Grounding rules: every number (price, %, date, metric) must trace to user text or injected blocks, or say it is not in context and do not guess.
3) If price snapshot and headlines conflict (e.g. bullish news vs weak price), state the tension and lower confidence instead of forcing one narrative.
4) One clarifying question only when the answer would change materially; otherwise state your assumption in one line.
5) Before a strong view, check it still holds using only injected data plus user text; if not, soften or recommend wait.
6) For multi-part questions, answer each part explicitly (numbered or short headers).
Reasoning discipline (internal; keep the reply concise):
1) Classify: trade action vs education vs news vs portfolio — lead with what they asked.
2) Ground every number (price, %, date) in user text, attachments, or injected blocks; otherwise say it is not in context.
3) If prices and headlines disagree, state the tension and reduce confidence instead of forcing one narrative.
4) Ask at most one clarifying question when it would materially change the answer; else state one-line assumptions.
5) Before a strong view, check it still holds using only injected data; if not, soften or recommend wait.
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    if USE_GROQ:
        print("Using Groq (free cloud). No Ollama needed.")
    else:
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(f"{OLLAMA_URL}/api/tags", timeout=2.0)
                if r.status_code != 200:
                    print("Warning: Ollama returned non-200. Is a model pulled? Run: ollama pull llama3.2")
        except Exception as e:
            print(f"Ollama not reachable. Set GROQ_API_KEY to use Groq instead, or start Ollama and run 'ollama pull {OLLAMA_MODEL}'.\n{e}")
    yield


app = FastAPI(title="Crypto ChatPal", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _build_messages(
    req: ChatRequest,
    price_snapshot: str = "",
    news_snapshot: str = "",
    price_grounding: str = "",
    news_grounding: str = "",
) -> list[dict]:
    """System prompt + grounding manifest + optional live prices + headlines + conversation history."""
    utc_now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
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
    if news_snapshot.strip():
        manifest_lines.append("Following message: RSS headline list (authoritative for those stories only).")
    else:
        manifest_lines.append("No RSS headline list message follows.")
    out.append({"role": "system", "content": "\n".join(manifest_lines)})
    if price_snapshot:
        out.append({"role": "system", "content": price_snapshot})
    if news_snapshot:
        out.append({"role": "system", "content": news_snapshot})
    for m in req.messages:
        out.append({"role": m.role, "content": m.content})
    return out


def _ollama_options() -> dict:
    return {"temperature": LLM_TEMPERATURE, "num_predict": LLM_MAX_TOKENS}


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
    news_snap = await fetch_news_snapshot_for_llm()
    messages = _build_messages(
        req,
        snapshot,
        news_snap,
        default_prices_grounding_note(),
        llm_news_grounding_note(),
    )

    if USE_GROQ:
        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                r = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
                    json={
                        "model": GROQ_MODEL,
                        "messages": messages,
                        "temperature": LLM_TEMPERATURE,
                        "max_tokens": LLM_MAX_TOKENS,
                    },
                )
                r.raise_for_status()
                data = r.json()
                content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "").strip()
                return ChatResponse(message=content, model=data.get("model", GROQ_MODEL))
            except httpx.HTTPStatusError as e:
                detail = e.response.text
                if e.response.status_code == 401:
                    detail = "Invalid GROQ_API_KEY. Get a free key at https://console.groq.com"
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
                async with client.stream(
                    "POST",
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
                    json={
                        "model": GROQ_MODEL,
                        "messages": messages,
                        "stream": True,
                        "temperature": LLM_TEMPERATURE,
                        "max_tokens": LLM_MAX_TOKENS,
                    },
                ) as r:
                    if r.status_code != 200:
                        raw = (await r.aread()).decode(errors="replace")
                        try:
                            err_j = json.loads(raw)
                            detail = err_j.get("error", {}).get("message") or raw
                        except json.JSONDecodeError:
                            detail = raw or r.reason_phrase
                        if r.status_code == 401:
                            detail = "Invalid GROQ_API_KEY. Get a free key at https://console.groq.com"
                        yield _ndjson_line({"error": detail})
                        return
                    async for line in r.aiter_lines():
                        if not line or line.startswith(":"):
                            continue
                        if not line.startswith("data: "):
                            continue
                        payload = line[6:].strip()
                        if payload == "[DONE]":
                            break
                        try:
                            obj = json.loads(payload)
                        except json.JSONDecodeError:
                            continue
                        choice0 = (obj.get("choices") or [{}])[0]
                        delta = choice0.get("delta") or {}
                        piece = delta.get("content") or ""
                        if piece:
                            yield _ndjson_line({"c": piece})
                    yield _ndjson_line({"done": True, "model": GROQ_MODEL})
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
    news_snap = await fetch_news_snapshot_for_llm()
    messages = _build_messages(
        req,
        snapshot,
        news_snap,
        default_prices_grounding_note(),
        llm_news_grounding_note(),
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
