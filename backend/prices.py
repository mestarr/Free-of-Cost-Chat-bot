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
from datetime import UTC, datetime

import httpx

from . import observability
from .redis_cache import REDIS_URL, cache_get_json, cache_set_json

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
# Sparklines update much slower than spot prices — 24h trend shape is stable for minutes.
SPARKLINE_TTL_SECONDS = float(os.getenv("SPARKLINE_CACHE_SECONDS", "300"))
# After a 429 we wait this many seconds before hitting CoinGecko again (serve stale in between).
_RATE_LIMIT_BACKOFF = max(TTL_SECONDS * 6, 60.0)
MAX_IDS_PER_REQUEST = 40
MAX_CACHE_BUCKETS = 24
_PRICE_REDIS_PREFIX = "ccp:price:v1:"
_SPARK_REDIS_PREFIX = "ccp:spark:v1:"
# Downsample 168 hourly points (CoinGecko sparkline_in_7d) to this many for UI.
_SPARK_POINTS = 24

# bucket_key -> {"ts": float, "data": dict | None, "retry_after": float}
_caches: dict[str, dict] = {}
_spark_cache: dict[str, dict] = {}
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
        "When the user asks for current prices, quote these numbers and say they are approximate spot prices, "
        "not a trading recommendation.\n" + "\n".join(lines)
    )


async def _fetch_upstream(ids_param: str) -> tuple[dict | None, float]:
    """Returns (data, retry_after).  data=None means rate-limited; retry_after is how
    many seconds to wait before trying again (0 = no hint)."""
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
            try:
                ra = float(r.headers.get("retry-after", 0))
            except (ValueError, TypeError):
                ra = 0.0
            return None, ra
        r.raise_for_status()
        return r.json(), 0.0


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

    # Fresh in-process hit
    if ent and ent.get("data") is not None and (now - ent["ts"]) < TTL_SECONDS:
        observability.inc_counter("price_cache_hit")
        return ent["data"]

    # Still within backoff window after a 429 — serve stale, don't call upstream
    if ent and ent.get("retry_after", 0.0) > now:
        observability.inc_counter("price_cache_hit")
        return ent.get("data") or {}

    if REDIS_URL:
        rkey = _PRICE_REDIS_PREFIX + bucket
        rd = await cache_get_json(rkey)
        if rd and isinstance(rd, dict) and rd:
            _evict_oldest_cache()
            _caches[bucket] = {"ts": now, "data": rd, "retry_after": 0.0}
            observability.inc_counter("price_cache_hit")
            return rd

    observability.inc_counter("price_cache_miss")
    try:
        data, hint = await _fetch_upstream(fetch_part)
        if data is None:
            # 429 — back off; update ts so TTL also resets to avoid immediate re-check
            backoff = now + (hint if hint > 0 else _RATE_LIMIT_BACKOFF)
            if ent:
                ent["ts"] = now
                ent["retry_after"] = backoff
            else:
                _caches[bucket] = {"ts": now, "data": None, "retry_after": backoff}
            if ent and ent.get("data") is not None:
                return ent["data"]
            return {}
        _evict_oldest_cache()
        _caches[bucket] = {"ts": now, "data": data, "retry_after": 0.0}
        if REDIS_URL:
            await cache_set_json(_PRICE_REDIS_PREFIX + bucket, data, int(max(1, TTL_SECONDS)))
        return data
    except Exception:
        if ent and ent.get("data") is not None:
            ent["ts"] = now  # also back off on generic errors
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
    )


async def fetch_prices_json(ids_csv: str | None = None) -> dict:
    """For GET /api/prices — optional `ids` query (comma-separated CoinGecko ids)."""
    return await get_price_data(ids_csv=ids_csv)


def _oil_closes_from_payload(payload: dict) -> list[float]:
    """Daily close prices from Yahoo chart result (ordered oldest → newest)."""
    try:
        result = (((payload or {}).get("chart") or {}).get("result") or [None])[0] or {}
        quotes = (result.get("indicators") or {}).get("quote") or []
        if not quotes or not isinstance(quotes, list):
            return []
        closes = (quotes[0] or {}).get("close")
        if not isinstance(closes, list):
            return []
        out: list[float] = []
        for p in closes:
            if p is None or isinstance(p, bool):
                continue
            if isinstance(p, int | float):
                fp = float(p)
                if fp != fp:  # NaN
                    continue
                out.append(fp)
        return out
    except Exception:
        return []


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
        closes = _oil_closes_from_payload(payload)
        spark: list[float] = []
        if len(closes) >= 2:
            spark = _downsample(closes, _SPARK_POINTS) if len(closes) > _SPARK_POINTS else closes
        return {
            "symbol": symbol,
            "label": label,
            "usd": float(price),
            "change_pct": chg_pct,
            "sparkline": spark,
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
                    params={"interval": "1d", "range": "1mo"},
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
            {"symbol": "CL=F", "label": "WTI Crude", "usd": None, "change_pct": None, "sparkline": []},
            {"symbol": "BZ=F", "label": "Brent Crude", "usd": None, "change_pct": None, "sparkline": []},
            {"symbol": "GC=F", "label": "Gold", "usd": None, "change_pct": None, "sparkline": []},
            {"symbol": "SI=F", "label": "Silver", "usd": None, "change_pct": None, "sparkline": []},
        ]
    return {
        "fetched_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
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


def _downsample(points: list[float], target: int) -> list[float]:
    """Uniform pick `target` points from `points` (preserves first + last)."""
    n = len(points)
    if n <= target or target < 2:
        return [float(p) for p in points if p is not None]
    step = (n - 1) / (target - 1)
    out: list[float] = []
    for i in range(target):
        out.append(float(points[round(i * step)]))
    return out


async def _fetch_sparklines_upstream(ids_param: str) -> tuple[dict | None, float]:
    """CoinGecko /coins/markets returns 7d sparkline in one shot. Slice to last ~24h."""
    url = "https://api.coingecko.com/api/v3/coins/markets"
    params = {
        "vs_currency": "usd",
        "ids": ids_param,
        "sparkline": "true",
        "price_change_percentage": "24h",
        "per_page": MAX_IDS_PER_REQUEST,
        "page": 1,
    }
    headers = {"Accept": "application/json", "User-Agent": "CryptoChatPal/1.0"}
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(url, params=params, headers=headers)
        if r.status_code == 429:
            try:
                ra = float(r.headers.get("retry-after", 0))
            except (ValueError, TypeError):
                ra = 0.0
            return None, ra
        r.raise_for_status()
        raw = r.json() or []
        out: dict[str, list[float]] = {}
        for coin in raw:
            if not isinstance(coin, dict):
                continue
            cid = coin.get("id")
            sp = (coin.get("sparkline_in_7d") or {}).get("price") or []
            if not isinstance(cid, str) or not isinstance(sp, list) or not sp:
                continue
            # Last 24 hourly points = last day
            last24 = [p for p in sp[-24:] if isinstance(p, int | float)]
            if len(last24) < 2:
                continue
            out[cid] = _downsample(last24, _SPARK_POINTS)
        return out, 0.0


async def fetch_sparklines_json(ids_csv: str | None = None) -> dict:
    """Returns { "bitcoin": [p1, p2, ...], ... } — 24h price series per coin (hourly, downsampled)."""
    ids_list = _sanitize_ids_list(ids_csv or "") or _default_id_list()
    bucket = _cache_bucket_key(ids_list)
    now = time.time()

    ent = _spark_cache.get(bucket)
    if ent and ent.get("data") is not None and (now - ent["ts"]) < SPARKLINE_TTL_SECONDS:
        return ent["data"]
    if ent and ent.get("retry_after", 0.0) > now:
        return ent.get("data") or {}

    if REDIS_URL:
        rd = await cache_get_json(_SPARK_REDIS_PREFIX + bucket)
        if isinstance(rd, dict) and rd:
            _spark_cache[bucket] = {"ts": now, "data": rd, "retry_after": 0.0}
            return rd

    try:
        data, hint = await _fetch_sparklines_upstream(",".join(ids_list))
        if data is None:
            backoff = now + (hint if hint > 0 else _RATE_LIMIT_BACKOFF)
            if ent:
                ent["ts"] = now
                ent["retry_after"] = backoff
            else:
                _spark_cache[bucket] = {"ts": now, "data": None, "retry_after": backoff}
            return ent.get("data") if ent else {}
        _spark_cache[bucket] = {"ts": now, "data": data, "retry_after": 0.0}
        if REDIS_URL:
            await cache_set_json(_SPARK_REDIS_PREFIX + bucket, data, int(SPARKLINE_TTL_SECONDS))
        return data
    except Exception:
        return ent.get("data") if ent and ent.get("data") else {}
