"""WebSocket /api/ws/live — must be registered before the catch-all StaticFiles mount."""
from __future__ import annotations

import asyncio
import json
import os
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .accounts import verify_api_key
from .fng import fetch_fear_greed_json
from .macro_radar import fetch_macro_radar_json
from .news import get_fed_news_api_payload, get_news_api_payload
from .onchain import fetch_onchain_markets_json
from .prices import fetch_oil_prices_json, fetch_prices_json

router = APIRouter()


def _ws_auth_ok(websocket: WebSocket) -> bool:
    mode = os.getenv("CCP_AUTH_MODE", "off").strip().lower()
    if mode != "required":
        return True
    token = (
        websocket.query_params.get("api_key")
        or websocket.headers.get("x-ccp-api-key")
        or websocket.headers.get("X-CCP-API-Key")
        or ""
    ).strip()
    return bool(token and verify_api_key(token))


@router.websocket("/api/ws/live")
async def websocket_live(websocket: WebSocket):
    """Push prices ~1s, news ~90s, macro ~5m; accepts {type: subscribe, ids: csv}."""
    if not _ws_auth_ok(websocket):
        await websocket.close(code=4401, reason="Unauthorized")
        return
    await websocket.accept()
    ids_csv = ""
    last_news = 0.0
    last_macro = 0.0
    try:
        while True:
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=1.0)
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    msg = None
                if isinstance(msg, dict) and msg.get("type") == "subscribe":
                    ids_csv = str(msg.get("ids") or "").strip()
            except TimeoutError:
                pass

            try:
                prices = await fetch_prices_json(ids_csv=ids_csv or None)
                await websocket.send_json({"type": "prices", "data": prices})
            except Exception:
                await websocket.send_json({"type": "prices", "data": {}, "error": "fetch_failed"})

            now = time.monotonic()
            if now - last_news >= 90:
                last_news = now
                try:
                    news = await get_news_api_payload(limit=25)
                    await websocket.send_json({"type": "news", "data": news})
                except Exception:
                    pass
            if now - last_macro >= 300:
                last_macro = now
                try:
                    oil = await fetch_oil_prices_json()
                    fed = await get_fed_news_api_payload(limit=8)
                    fng = await fetch_fear_greed_json()
                    onchain = await fetch_onchain_markets_json(ids_csv=ids_csv or None)
                    radar = await fetch_macro_radar_json()
                    await websocket.send_json(
                        {
                            "type": "macro",
                            "oil": oil,
                            "fed": fed,
                            "fng": fng,
                            "onchain": onchain,
                            "radar": radar,
                        }
                    )
                except Exception:
                    pass
    except WebSocketDisconnect:
        return
    except Exception:
        try:
            await websocket.close()
        except Exception:
            pass
