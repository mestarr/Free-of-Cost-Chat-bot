"""Crypto Fear & Greed Index (Alternative.me public API, no key)."""
from __future__ import annotations

import os
import time
from datetime import UTC, datetime

import httpx

_FNG_URL = "https://api.alternative.me/fng/"
try:
    _FNG_CACHE_SECONDS = max(30.0, min(3600.0, float(os.getenv("FNG_CACHE_SECONDS", "120"))))
except ValueError:
    _FNG_CACHE_SECONDS = 120.0

_cache: dict[str, object] = {"ts": 0.0, "data": None}


def _parse_next_update(raw: object) -> int | None:
    if raw is None:
        return None
    try:
        n = int(str(raw).strip())
        return max(0, min(n, 86400 * 7))
    except (ValueError, TypeError):
        return None


async def fetch_fear_greed_json() -> dict:
    """
    Current index 0–100 plus label. Cached in-process (see FNG_CACHE_SECONDS).
    """
    now = time.time()
    ent = _cache.get("data")
    age = now - float(_cache.get("ts") or 0.0)
    if isinstance(ent, dict) and ent.get("value") is not None and age < _FNG_CACHE_SECONDS:
        return ent

    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            r = await client.get(
                _FNG_URL,
                params={"limit": "1"},
                headers={"Accept": "application/json", "User-Agent": "CryptoChatPal/1.0"},
            )
            r.raise_for_status()
            body = r.json() or {}
    except Exception:
        if isinstance(ent, dict) and ent.get("value") is not None:
            return ent  # type: ignore[return-value]
        return {
            "value": None,
            "classification": None,
            "updated_at": None,
            "next_update_in_seconds": None,
            "source": "alternative.me",
            "error": "unavailable",
        }

    rows = body.get("data")
    if not isinstance(rows, list) or not rows:
        out = {
            "value": None,
            "classification": None,
            "updated_at": None,
            "next_update_in_seconds": None,
            "source": "alternative.me",
            "error": "empty",
        }
        _cache["ts"] = now
        _cache["data"] = out
        return out

    d0 = rows[0] if isinstance(rows[0], dict) else {}
    try:
        val = int(str(d0.get("value", "")).strip())
    except (ValueError, TypeError):
        val = None
    if val is not None:
        val = max(0, min(100, val))

    classification = (d0.get("value_classification") or "").strip() or None
    ts_raw = d0.get("timestamp")
    updated_at = None
    try:
        ts_i = int(str(ts_raw).strip())
        updated_at = datetime.fromtimestamp(ts_i, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, TypeError, OSError):
        pass

    out = {
        "value": val,
        "classification": classification,
        "updated_at": updated_at,
        "next_update_in_seconds": _parse_next_update(d0.get("time_until_update")),
        "source": "alternative.me Crypto Fear & Greed Index",
    }
    _cache["ts"] = now
    _cache["data"] = out
    return out
