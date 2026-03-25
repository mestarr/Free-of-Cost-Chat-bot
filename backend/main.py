"""
Free crypto-focused AI chatbot backend.
Uses Groq (free cloud) if GROQ_API_KEY is set; otherwise Ollama (local).
"""
import os
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")
USE_GROQ = bool(GROQ_API_KEY)

SYSTEM_PROMPT = """You are a helpful cryptocurrency assistant. You answer questions about:
- Bitcoin, Ethereum, and other major cryptocurrencies
- DeFi, NFTs, layer-2 solutions, and blockchain basics
- Wallets, security, and best practices
- Market concepts (volatility, halving, staking, etc.)
- General crypto terminology and how things work

Keep answers clear and factual. If you're unsure, say so. Do not give financial advice or price predictions.
Respond in the same language the user writes in unless they ask for another language."""


class ChatMessage(BaseModel):
    role: str
    content: str


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


app = FastAPI(title="Free Crypto Chatbot", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _build_messages(req: ChatRequest) -> list[dict]:
    """System prompt + conversation history."""
    out = [{"role": "system", "content": SYSTEM_PROMPT}]
    for m in req.messages:
        out.append({"role": m.role, "content": m.content})
    return out


@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """Send conversation to Groq or Ollama with crypto-focused system prompt."""
    messages = _build_messages(req)

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
