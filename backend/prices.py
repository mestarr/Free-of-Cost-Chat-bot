"""
Live crypto spot prices via CoinGecko public API (free tier, no API key).
https://www.coingecko.com/en/api

Fetches are cached (default 10s) to respect rate limits. The UI may poll /api/prices
every second; the server returns cached data between upstream refreshes.

GET /api/prices?ids=bitcoin,ethereum,... uses that set (sanitized). Omit `ids` for
the default list (also used for the chat system snapshot).
"""
import os
import re
import time
from datetime import datetime, timezone

import httpx

# CoinGecko `ids` (not symbols). Extend as needed.
DEFAULT_IDS = (
    "bitcoin,ethereum,solana,ripple,cardano,binancecoin,dogecoin,polkadot,sui"
)

# Short human labels for chat context
LABELS = {
    "bitcoin": "Bitcoin (BTC)",
    "ethereum": "Ethereum (ETH)",
    "solana": "Solana (SOL)",
    "ripple": "XRP",
    "cardano": "Cardano (ADA)",
    "binancecoin": "BNB",
    "dogecoin": "Dogecoin (DOGE)",
    "polkadot": "Polkadot (DOT)",
    "sui": "Sui (SUI)",
}

TTL_SECONDS = float(os.getenv("PRICE_CACHE_SECONDS", "10"))
OIL_TTL_SECONDS = float(os.getenv("OIL_CACHE_SECONDS", "300"))
MAX_IDS_PER_REQUEST = 40
MAX_CACHE_BUCKETS = 24

# bucket_key (sorted ids joined) -> {"ts": float, "data": dict | None}
_caches: dict[str, dict] = {}
_oil_cache: dict[str, object] = {"ts": 0.0, "data": {}}


def _default_id_list() -> list[str]:
    return [x.strip() for x in DEFAULT_IDS.split(",") if x.strip()]


def _sanitize_ids_list(ids_csv: str) -> list[str]:
    """Unique CoinGecko ids in request order; empty if none valid."""
    out: list[str] = []
    seen: set[str] = set()
    for raw in ids_csv.split(","):
        part = raw.strip().lower()
        if not part or part in seen:
            continue
        if len(part) > 64:
            continue
        if not re.match(r"^[a-z0-9_-]+$", part):
            continue
        seen.add(part)
        out.append(part)
        if len(out) >= MAX_IDS_PER_REQUEST:
            break
    return out


def _cache_bucket_key(ids_list: list[str]) -> str:
    return ",".join(sorted(ids_list))


def _evict_oldest_cache() -> None:
    if len(_caches) <= MAX_CACHE_BUCKETS:
        return
    sorted_keys = sorted(_caches.keys(), key=lambda k: _caches[k]["ts"])
    for k in sorted_keys[: len(_caches) - MAX_CACHE_BUCKETS + 1]:
        del _caches[k]


def _snapshot_from_data(data: dict) -> str:
    lines: list[str] = []
    for cid in DEFAULT_IDS.split(","):
        cid = cid.strip()
        row = data.get(cid)
        if not row:
            continue
        usd = row.get("usd")
        if usd is None:
            continue
        label = LABELS.get(cid, cid.replace("-", " ").title())
        ch = row.get("usd_24h_change")
        if ch is not None:
            lines.append(f"- {label}: ${usd:,.2f} USD (24h change: {ch:+.2f}%)")
        else:
            lines.append(f"- {label}: ${usd:,.2f} USD")

    if not lines:
        return ""

    return (
        "Live market snapshot (spot prices in USD from CoinGecko; refreshed periodically). "
        "When the user asks for current prices, quote these numbers and say they are approximate spot prices, not a trading recommendation.\n"
        + "\n".join(lines)
    )


async def _fetch_upstream(ids_param: str) -> dict | None:
    url = "https://api.coingecko.com/api/v3/simple/price"
    params = {
        "ids": ids_param,
        "vs_currencies": "usd",
        "include_24hr_change": "true",
    }
    headers = {"Accept": "application/json", "User-Agent": "CryptoChatPal/1.0"}
    async with httpx.AsyncClient(timeout=12.0) as client:
        r = await client.get(url, params=params, headers=headers)
        if r.status_code == 429:
            return None
        r.raise_for_status()
        return r.json()


async def get_price_data(ids_csv: str | None = None) -> dict:
    """
    Returns CoinGecko simple/price JSON. Cached per unique id-set for TTL_SECONDS.
    If ids_csv is missing/invalid, uses DEFAULT_IDS.
    """
    ids_list: list[str]
    if ids_csv and ids_csv.strip():
        ids_list = _sanitize_ids_list(ids_csv)
    else:
        ids_list = []
    if not ids_list:
        ids_list = _default_id_list()

    fetch_part = ",".join(ids_list)
    bucket = _cache_bucket_key(ids_list)
    now = time.time()
    ent = _caches.get(bucket)
    if ent and ent.get("data") is not None and (now - ent["ts"]) < TTL_SECONDS:
        return ent["data"]

    try:
        data = await _fetch_upstream(fetch_part)
        if data is None:
            if ent and ent.get("data") is not None:
                return ent["data"]
            return {}
        _evict_oldest_cache()
        _caches[bucket] = {"ts": now, "data": data}
        return data
    except Exception:
        if ent and ent.get("data") is not None:
            return ent["data"]
        return {}


async def fetch_live_price_snapshot() -> str:
    """System message string with USD spot + 24h change, or empty if unavailable."""
    data = await get_price_data(None)
    if not data:
        return ""
    return _snapshot_from_data(data)


def default_prices_grounding_note() -> str:
    """One line for the LLM: what the price snapshot represents and how fresh it is."""
    key = _cache_bucket_key(_default_id_list())
    ent = _caches.get(key)
    if not ent or not ent.get("data"):
        return "Price feed: no cached CoinGecko USD data for the default watchlist (do not quote spot prices)."
    age = max(0.0, time.time() - float(ent["ts"]))
    return (
        f"Price feed: CoinGecko USD spot + 24h change for the default watchlist only; "
        f"cache ~{int(age)}s old (refreshed about every {int(TTL_SECONDS)}s)."
    """How fresh the default watchlist CoinGecko snapshot is (for LLM grounding)."""
    key = _cache_bucket_key(_default_id_list())
    ent = _caches.get(key)
    if not ent or not ent.get("data"):
        return "Live prices: unavailable (no cached CoinGecko data for default set)."
    age = max(0.0, time.time() - float(ent["ts"]))
    return (
        f"Live prices: CoinGecko USD spot for default assets; cache age ~{int(age)}s "
        f"(refreshed about every {int(TTL_SECONDS)}s)."
    )


async def fetch_prices_json(ids_csv: str | None = None) -> dict:
    """For GET /api/prices — optional `ids` query (comma-separated CoinGecko ids)."""
    return await get_price_data(ids_csv=ids_csv)


def _oil_row_from_chart(payload: dict, symbol: str, label: str) -> dict | None:
    try:
        result = (((payload or {}).get("chart") or {}).get("result") or [None])[0] or {}
        meta = result.get("meta") or {}
        price = meta.get("regularMarketPrice")
        prev = meta.get("chartPreviousClose")
        if price is None:
            return None
        chg_pct = None
        if prev not in (None, 0):
            chg_pct = ((price - prev) / prev) * 100.0
        return {
            "symbol": symbol,
            "label": label,
            "usd": float(price),
            "change_pct": chg_pct,
        }
    except Exception:
        return None


async def _fetch_oil_prices_upstream() -> dict:
    # Yahoo Finance chart API (public, delayed quotes)
    specs = [
        ("CL=F", "WTI Crude"),
        ("BZ=F", "Brent Crude"),
        ("GC=F", "Gold"),
        ("SI=F", "Silver"),
    ]
    out: list[dict] = []
    async with httpx.AsyncClient(timeout=12.0) as client:
        for symbol, label in specs:
            try:
                url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
                r = await client.get(
                    url,
                    params={"interval": "1d", "range": "5d"},
                    headers={"User-Agent": "CryptoChatPal/1.0", "Accept": "application/json"},
                )
                if r.status_code != 200:
                    continue
                row = _oil_row_from_chart(r.json(), symbol=symbol, label=label)
                if row:
                    out.append(row)
            except Exception:
                continue
    # Keep stable structure for UI even if upstream is rate-limited/unavailable.
    if not out:
        out = [
            {"symbol": "CL=F", "label": "WTI Crude", "usd": None, "change_pct": None},
            {"symbol": "BZ=F", "label": "Brent Crude", "usd": None, "change_pct": None},
            {"symbol": "GC=F", "label": "Gold", "usd": None, "change_pct": None},
            {"symbol": "SI=F", "label": "Silver", "usd": None, "change_pct": None},
        ]
    return {
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "items": out,
    }


async def fetch_oil_prices_json() -> dict:
    """Top-panel macro data: oil + metals benchmarks (Yahoo delayed quotes)."""
    now = time.time()
    cached = _oil_cache.get("data")
    if cached and (now - float(_oil_cache.get("ts") or 0.0)) < OIL_TTL_SECONDS:
        return cached  # type: ignore[return-value]

    try:
        data = await _fetch_oil_prices_upstream()
        if not data.get("items") and cached:
            return cached  # type: ignore[return-value]
        _oil_cache["ts"] = now
        _oil_cache["data"] = data
        return data
    except Exception:
        if cached:
            return cached  # type: ignore[return-value]
        return {"fetched_at": "", "items": []}
