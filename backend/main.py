"""
Free crypto-focused AI chatbot backend.
Uses Groq (free cloud) if GROQ_API_KEY is set; otherwise Ollama (local).
"""
import os
from contextlib import asynccontextmanager

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .news import fetch_news_snapshot_for_llm, get_fed_news_api_payload, get_news_api_payload
from .prices import fetch_live_price_snapshot, fetch_oil_prices_json, fetch_prices_json

# Load project-root .env (same folder as backend/)
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_root, ".env"))

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")
USE_GROQ = bool(GROQ_API_KEY)

SYSTEM_PROMPT = """You are Crypto ChatPal, a direct crypto market analyst. Be clear, specific, and practical. No fluff.

Core behavior:
- You ARE allowed to give a directional trading opinion when asked (buy / sell / hold), but present it as probabilistic analysis, never certainty.
- Use only available evidence: user context, injected live prices, and injected headlines/news. Do not invent data.
- If data is missing or stale, explicitly say so and lower confidence.
- Respond in the same language as the user unless they ask otherwise.

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


def _build_messages(req: ChatRequest, price_snapshot: str = "", news_snapshot: str = "") -> list[dict]:
    """System prompt + optional live prices + headlines + conversation history."""
    out: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    if price_snapshot:
        out.append({"role": "system", "content": price_snapshot})
    if news_snapshot:
        out.append({"role": "system", "content": news_snapshot})
    for m in req.messages:
        out.append({"role": m.role, "content": m.content})
    return out


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
    messages = _build_messages(req, snapshot, news_snap)

    if USE_GROQ:
        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                r = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
                    json={"model": GROQ_MODEL, "messages": messages},
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
                    json={"model": OLLAMA_MODEL, "messages": messages, "stream": False},
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


# Serve frontend
static_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.isdir(static_dir):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
