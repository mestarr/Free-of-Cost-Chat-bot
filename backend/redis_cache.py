"""Optional Redis read-through cache (shared across workers). No-op when REDIS_URL unset."""
from __future__ import annotations

import json
import os
from typing import Any

REDIS_URL = os.getenv("REDIS_URL", "").strip()
_client: Any = None


async def get_client():
    global _client
    if not REDIS_URL:
        return None
    if _client is None:
        try:
            import redis.asyncio as redis
        except ImportError:
            return None
        _client = redis.from_url(REDIS_URL, decode_responses=True)
    return _client


async def close_client() -> None:
    global _client
    if _client is not None:
        try:
            aclose = getattr(_client, "aclose", None)
            if callable(aclose):
                await aclose()
            else:
                await _client.close()
        except Exception:
            pass
        _client = None


async def cache_get_json(key: str) -> dict[str, Any] | None:
    r = await get_client()
    if not r:
        return None
    try:
        raw = await r.get(key)
        if not raw:
            return None
        return json.loads(raw)
    except Exception:
        return None


async def cache_set_json(key: str, value: dict[str, Any], ttl_seconds: int) -> None:
    r = await get_client()
    if not r:
        return
    try:
        ttl = max(1, int(ttl_seconds))
        await r.setex(key, ttl, json.dumps(value, ensure_ascii=False))
    except Exception:
        pass


async def ping() -> bool:
    r = await get_client()
    if not r:
        return False
    try:
        return bool(await r.ping())
    except Exception:
        return False
