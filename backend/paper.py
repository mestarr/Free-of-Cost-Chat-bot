"""
Paper trading / backtest helpers: infer asset, fetch historical USD, score vs emit_trade_analysis view.
"""
from __future__ import annotations

import re
import time
from typing import Any

import httpx

from . import observability
from .prices import _sanitize_ids_list

_HORIZON_SECONDS = {"h24": 24 * 3600, "d7": 7 * 24 * 3600}

# CoinGecko id aliases for inference from user text / view strings.
_COIN_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("bitcoin", re.compile(r"\b(btc|bitcoin)\b", re.I)),
    ("ethereum", re.compile(r"\b(eth|ethereum)\b", re.I)),
    ("solana", re.compile(r"\b(sol|solana)\b", re.I)),
    ("ripple", re.compile(r"\b(xrp|ripple)\b", re.I)),
    ("cardano", re.compile(r"\b(ada|cardano)\b", re.I)),
    ("binancecoin", re.compile(r"\b(bnb|binancecoin)\b", re.I)),
    ("dogecoin", re.compile(r"\b(doge|dogecoin)\b", re.I)),
    ("polkadot", re.compile(r"\b(dot|polkadot)\b", re.I)),
    ("sui", re.compile(r"\b(sui)\b", re.I)),
]

# chart range cache: coin + window -> {"ts": float, "points": list[tuple[int, float]]}
_chart_cache: dict[str, dict[str, Any]] = {}
_CHART_CACHE_TTL = 3600.0
_MAX_CHART_BUCKETS = 48


def infer_coin_id(*texts: str | None) -> str | None:
    """Best-effort CoinGecko id from trade fields or user message."""
    blob = " ".join(t for t in texts if t and str(t).strip()).strip()
    if not blob:
        return None
    for cid, pat in _COIN_PATTERNS:
        if pat.search(blob):
            return cid
    return None


def normalize_coin_id(raw: str | None) -> str | None:
    if not raw or not str(raw).strip():
        return None
    ids = _sanitize_ids_list(str(raw).strip().lower())
    return ids[0] if ids else None


def classify_view_bias(view: str | None) -> str:
    """long | short | neutral — maps Buy/Sell/Hold style views."""
    v = (view or "").strip().lower()
    if not v:
        return "neutral"
    if any(x in v for x in ("sell", "reduce", "short", "exit", "trim")):
        return "short"
    if "no trade" in v or "wait" in v and "buy" not in v and "sell" not in v:
        return "neutral"
    if any(x in v for x in ("buy", "long", "accumulate", "add")):
        return "long"
    if "hold" in v or "neutral" in v:
        return "neutral"
    return "neutral"


def score_outcome(bias: str, pct_change: float) -> tuple[str, int]:
    """
    Compare directional view vs realized % move (exit vs entry).
    Returns (verdict, score) where verdict is aligned | mixed | missed.
    """
    pct = float(pct_change)
    if bias == "long":
        if pct >= 1.0:
            return "aligned", 100
        if pct <= -2.0:
            return "missed", 0
        return "mixed", 50
    if bias == "short":
        if pct <= -1.0:
            return "aligned", 100
        if pct >= 2.0:
            return "missed", 0
        return "mixed", 50
    if abs(pct) < 1.5:
        return "aligned", 100
    if abs(pct) >= 5.0:
        return "missed", 0
    return "mixed", 50


def _cache_key(coin_id: str, from_s: int, to_s: int) -> str:
    return f"{coin_id}:{from_s}:{to_s}"


def _evict_chart_cache() -> None:
    if len(_chart_cache) <= _MAX_CHART_BUCKETS:
        return
    keys = sorted(_chart_cache.keys(), key=lambda k: float(_chart_cache[k].get("ts") or 0))
    for k in keys[: len(_chart_cache) - _MAX_CHART_BUCKETS + 1]:
        del _chart_cache[k]


async def _fetch_chart_range(coin_id: str, from_s: int, to_s: int) -> list[tuple[int, float]]:
    """USD prices [[ms, price], ...] from CoinGecko market_chart/range."""
    key = _cache_key(coin_id, from_s, to_s)
    now = time.time()
    ent = _chart_cache.get(key)
    if ent and (now - float(ent.get("ts") or 0)) < _CHART_CACHE_TTL:
        return list(ent.get("points") or [])

    url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart/range"
    params = {"vs_currency": "usd", "from": str(from_s), "to": str(to_s)}
    points: list[tuple[int, float]] = []
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(url, params=params)
            if r.status_code == 429:
                observability.log_event("coingecko_rate_limit", path="paper_chart_range")
                return points
            r.raise_for_status()
            body = r.json()
            for row in body.get("prices") or []:
                if not isinstance(row, list) or len(row) < 2:
                    continue
                try:
                    ts_ms = int(row[0])
                    px = float(row[1])
                except (TypeError, ValueError):
                    continue
                if px == px and px > 0:
                    points.append((ts_ms, px))
    except Exception:
        return points

    _chart_cache[key] = {"ts": now, "points": points}
    _evict_chart_cache()
    return points


def _price_near(points: list[tuple[int, float]], target_ms: int) -> float | None:
    if not points:
        return None
    best: tuple[int, float] | None = None
    best_delta = 10**18
    for ts_ms, px in points:
        d = abs(ts_ms - target_ms)
        if d < best_delta:
            best_delta = d
            best = (ts_ms, px)
    return best[1] if best else None


async def fetch_usd_near_timestamp(coin_id: str, at_ms: int) -> float | None:
    """Spot USD near a past timestamp (2h window around at_ms)."""
    cid = normalize_coin_id(coin_id)
    if not cid:
        return None
    at_s = max(0, int(at_ms // 1000))
    window = 7200
    points = await _fetch_chart_range(cid, at_s - window, at_s + window)
    return _price_near(points, at_ms)


async def evaluate_paper_outcome(
    *,
    coin_id: str,
    at_ms: int,
    horizon: str,
    view: str | None = None,
    entry_usd: float | None = None,
) -> dict[str, Any]:
    """
    Score a paper trade at entry time `at_ms` vs exit at at_ms + horizon (h24 | d7).
    """
    cid = normalize_coin_id(coin_id)
    if not cid:
        raise ValueError("invalid_coin_id")
    hz = (horizon or "h24").strip().lower()
    if hz not in _HORIZON_SECONDS:
        raise ValueError("invalid_horizon")
    horizon_ms = _HORIZON_SECONDS[hz] * 1000
    now_ms = int(time.time() * 1000)
    exit_ms = int(at_ms) + horizon_ms
    if exit_ms > now_ms:
        return {
            "ready": False,
            "horizon": hz,
            "coin_id": cid,
            "at_ms": at_ms,
            "check_at_ms": exit_ms,
            "wait_ms": exit_ms - now_ms,
        }

    entry = float(entry_usd) if entry_usd is not None and entry_usd > 0 else None
    if entry is None:
        entry_px = await fetch_usd_near_timestamp(cid, at_ms)
        entry = entry_px
    exit_px = await fetch_usd_near_timestamp(cid, exit_ms)

    if entry is None or exit_px is None or entry <= 0:
        return {
            "ready": True,
            "horizon": hz,
            "coin_id": cid,
            "at_ms": at_ms,
            "check_at_ms": exit_ms,
            "error": "price_unavailable",
            "entry_usd": entry,
            "exit_usd": exit_px,
        }

    pct = ((exit_px - entry) / entry) * 100.0
    bias = classify_view_bias(view)
    verdict, score = score_outcome(bias, pct)
    return {
        "ready": True,
        "horizon": hz,
        "coin_id": cid,
        "at_ms": at_ms,
        "check_at_ms": exit_ms,
        "entry_usd": round(entry, 6),
        "exit_usd": round(exit_px, 6),
        "pct_change": round(pct, 4),
        "view_bias": bias,
        "verdict": verdict,
        "score": score,
        "evaluated_at_ms": now_ms,
    }
