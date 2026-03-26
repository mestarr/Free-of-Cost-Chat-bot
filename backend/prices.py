"""
Live crypto spot prices via CoinGecko public API (free tier, no API key).
https://www.coingecko.com/en/api

Fetches are cached (default 10s) to respect rate limits. The UI may poll /api/prices
every second; the server returns cached data between upstream refreshes.
"""
import os
import time

import httpx

# CoinGecko `ids` (not symbols). Extend as needed.
DEFAULT_IDS = (
    "bitcoin,ethereum,solana,ripple,cardano,binancecoin,dogecoin,polkadot"
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
}

TTL_SECONDS = float(os.getenv("PRICE_CACHE_SECONDS", "10"))

_cache: dict = {"ts": 0.0, "data": None}  # data: dict from CoinGecko simple/price


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


async def _fetch_upstream() -> dict | None:
    url = "https://api.coingecko.com/api/v3/simple/price"
    params = {
        "ids": DEFAULT_IDS,
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


async def get_price_data() -> dict:
    """
    Returns CoinGecko simple/price JSON. Cached for TTL_SECONDS; one upstream call
    updates both chat snapshot and /api/prices responses.
    """
    now = time.time()
    if _cache["data"] is not None and (now - _cache["ts"]) < TTL_SECONDS:
        return _cache["data"]

    try:
        data = await _fetch_upstream()
        if data is None:
            if _cache["data"] is not None:
                return _cache["data"]
            return {}
        _cache["ts"] = now
        _cache["data"] = data
        return data
    except Exception:
        if _cache["data"] is not None:
            return _cache["data"]
        return {}


async def fetch_live_price_snapshot() -> str:
    """System message string with USD spot + 24h change, or empty if unavailable."""
    data = await get_price_data()
    if not data:
        return ""
    return _snapshot_from_data(data)


async def fetch_prices_json() -> dict:
    """For GET /api/prices — same cache as chat snapshot."""
    return await get_price_data()
