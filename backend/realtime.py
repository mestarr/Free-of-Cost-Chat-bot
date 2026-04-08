"""
WebSocket feed: push prices (~1 Hz), news (~90 s), macro oil/Fed (~5 min).
Client sends {"type":"subscribe","ids":"bitcoin,ethereum,..."} to match the UI watchlist + portfolio.
"""
from __future__ import annotations

import asyncio
import json
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .news import get_fed_news_api_payload, get_news_api_payload
from .prices import fetch_oil_prices_json, get_price_data

router = APIRouter()

PRICE_TICK_SEC = 1.0
NEWS_PUSH_SEC = 90.0
MACRO_PUSH_SEC = 300.0


@router.websocket("/api/ws/live")
async def websocket_live(websocket: WebSocket):
    await websocket.accept()
    ids_csv = ""
    last_news_mono = 0.0
    last_macro_mono = 0.0
    try:
        while True:
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=PRICE_TICK_SEC)
                if raw:
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        msg = None
                    if isinstance(msg, dict) and msg.get("type") == "subscribe":
                        ids = msg.get("ids")
                        ids_csv = str(ids).strip() if ids is not None else ""
            except asyncio.TimeoutError:
                pass

            now = time.monotonic()

            try:
                data = await get_price_data(ids_csv if ids_csv else None)
                await websocket.send_json({"type": "prices", "data": data})
            except Exception as e:
                await websocket.send_json({"type": "error", "scope": "prices", "detail": str(e)[:240]})

            if now - last_news_mono >= NEWS_PUSH_SEC:
                last_news_mono = now
                try:
                    payload = await get_news_api_payload()
                    await websocket.send_json({"type": "news", "data": payload})
                except Exception as e:
                    await websocket.send_json({"type": "error", "scope": "news", "detail": str(e)[:240]})

            if now - last_macro_mono >= MACRO_PUSH_SEC:
                last_macro_mono = now
                try:
                    oil = await fetch_oil_prices_json()
                    fed = await get_fed_news_api_payload(limit=8)
                    await websocket.send_json({"type": "macro", "oil": oil, "fed": fed})
                except Exception as e:
                    await websocket.send_json({"type": "error", "scope": "macro", "detail": str(e)[:240]})
    except WebSocketDisconnect:
        return
