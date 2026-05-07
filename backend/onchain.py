"""
Exchange-derivatives & flow proxies (Binance USDT-M futures, public APIs) + optional whale transfers (Whale Alert).

This is not full on-chain attribution: funding/OI/taker ratios come from Binance futures REST.
Optional WHALE_ALERT_API_KEY enables large-transfer highlights (see https://whale-alert.io).
"""
from __future__ import annotations

import asyncio
import os
import re
import time
from datetime import UTC, datetime
from typing import Any

import httpx

from .prices import DEFAULT_IDS
from .redis_cache import cache_get_json, cache_set_json

try:
    _ONCHAIN_TTL = max(30.0, min(600.0, float(os.getenv("ONCHAIN_CACHE_SECONDS", "90"))))
except ValueError:
    _ONCHAIN_TTL = 90.0

BINANCE_FAPI = "https://fapi.binance.com"
WHALE_ALERT_URL = "https://api.whale-alert.io/v1/transactions"
_ONCHAIN_REDIS_PREFIX = "ccp:onchain:v2:"

# CoinGecko id -> (ticker, Binance USDT perpetual symbol)
_CG_BINANCE: dict[str, tuple[str, str]] = {
    "bitcoin": ("BTC", "BTCUSDT"),
    "ethereum": ("ETH", "ETHUSDT"),
    "solana": ("SOL", "SOLUSDT"),
    "ripple": ("XRP", "XRPUSDT"),
    "cardano": ("ADA", "ADAUSDT"),
    "binancecoin": ("BNB", "BNBUSDT"),
    "dogecoin": ("DOGE", "DOGEUSDT"),
    "polkadot": ("DOT", "DOTUSDT"),
    "sui": ("SUI", "SUIUSDT"),
    "chainlink": ("LINK", "LINKUSDT"),
    "avalanche-2": ("AVAX", "AVAXUSDT"),
    "matic-network": ("MATIC", "MATICUSDT"),
    "litecoin": ("LTC", "LTCUSDT"),
    "uniswap": ("UNI", "UNIUSDT"),
    "cosmos": ("ATOM", "ATOMUSDT"),
    "near": ("NEAR", "NEARUSDT"),
    "aptos": ("APT", "APTUSDT"),
    "arbitrum": ("ARB", "ARBUSDT"),
    "optimism": ("OP", "OPUSDT"),
    "stellar": ("XLM", "XLMUSDT"),
    "monero": ("XMR", "XMRUSDT"),
    "tron": ("TRX", "TRXUSDT"),
    "shiba-inu": ("SHIB", "SHIBUSDT"),
    "internet-computer": ("ICP", "ICPUSDT"),
    "filecoin": ("FIL", "FILUSDT"),
    "hedera-hashgraph": ("HBAR", "HBARUSDT"),
    "render-token": ("RNDR", "RNDRUSDT"),
    "immutable-x": ("IMX", "IMXUSDT"),
    "the-graph": ("GRT", "GRTUSDT"),
    "maker": ("MKR", "MKRUSDT"),
}

_HEADERS = {"User-Agent": "CryptoChatPal/1.0", "Accept": "application/json"}

# bucket_key -> {"ts": float, "data": dict}
_memory: dict[str, dict[str, Any]] = {}
_MAX_MEM_BUCKETS = 20


def _sanitize_ids_csv(ids_csv: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in ids_csv.split(","):
        part = raw.strip().lower()
        if not part or part in seen:
            continue
        if len(part) > 64 or not re.match(r"^[a-z0-9_-]+$", part):
            continue
        seen.add(part)
        out.append(part)
        if len(out) >= 40:
            break
    return out


def _ids_for_query(ids_csv: str | None) -> list[str]:
    if ids_csv and str(ids_csv).strip():
        return _sanitize_ids_csv(str(ids_csv))
    return [x.strip() for x in DEFAULT_IDS.split(",") if x.strip()]


def _pairs_in_order(ids: list[str]) -> list[tuple[str, str, str]]:
    pairs: list[tuple[str, str, str]] = []
    for cid in ids:
        if cid in _CG_BINANCE:
            sym, bsym = _CG_BINANCE[cid]
            pairs.append((cid, sym, bsym))
    return pairs


def _parse_f(v: Any) -> float | None:
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


def _first_row_list(data: Any) -> dict | None:
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return data[0]
    return None


def _fmt_ts_ms(ms: Any) -> str | None:
    try:
        m = int(ms)
        return datetime.fromtimestamp(m / 1000.0, tz=UTC).strftime("%Y-%m-%d %H:%MZ")
    except (TypeError, ValueError, OSError):
        return None


def _explorer_tx_url(blockchain: str, tx_hash: str) -> str | None:
    b = (blockchain or "").lower()
    h = (tx_hash or "").strip()
    if not h:
        return None
    if b == "bitcoin":
        return f"https://mempool.space/tx/{h}"
    if b in ("ethereum", "eth"):
        return f"https://etherscan.io/tx/{h}"
    if b in ("ripple", "xrp"):
        return f"https://xrpscan.com/tx/{h}"
    if b == "tron":
        return f"https://tronscan.org/#/transaction/{h}"
    return None


def _evict_memory() -> None:
    if len(_memory) <= _MAX_MEM_BUCKETS:
        return
    oldest = sorted(_memory.keys(), key=lambda k: float(_memory[k].get("ts") or 0.0))
    for k in oldest[: len(_memory) - _MAX_MEM_BUCKETS + 1]:
        _memory.pop(k, None)


async def _fetch_binance_symbol(
    client: httpx.AsyncClient, cg_id: str, sym: str, bsym: str
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": cg_id,
        "sym": sym,
        "binance_symbol": bsym,
        "mark_price": None,
        "index_price": None,
        "funding_rate": None,
        "funding_pct_per_interval": None,
        "next_funding_time_ms": None,
        "next_funding_label": None,
        "open_interest_contracts": None,
        "open_interest_usd_est": None,
        "taker_buy_sell_ratio_5m": None,
        "long_short_account_ratio_5m": None,
    }

    async def safe_get(path: str, params: dict[str, Any] | None = None) -> Any:
        try:
            r = await client.get(f"{BINANCE_FAPI}{path}", params=params or {}, timeout=12.0)
            r.raise_for_status()
            return r.json()
        except Exception:
            return None

    pj, oij, tkj, glj = await asyncio.gather(
        safe_get("/fapi/v1/premiumIndex", {"symbol": bsym}),
        safe_get("/fapi/v1/openInterest", {"symbol": bsym}),
        safe_get("/futures/data/takerlongshortRatio", {"symbol": bsym, "period": "5m", "limit": 1}),
        safe_get(
            "/futures/data/globalLongShortAccountRatio", {"symbol": bsym, "period": "5m", "limit": 1}
        ),
    )

    if isinstance(pj, dict):
        row["mark_price"] = _parse_f(pj.get("markPrice"))
        row["index_price"] = _parse_f(pj.get("indexPrice"))
        fr = _parse_f(pj.get("lastFundingRate"))
        row["funding_rate"] = fr
        if fr is not None:
            row["funding_pct_per_interval"] = round(fr * 100.0, 6)
        try:
            nft = int(pj.get("nextFundingTime"))
            row["next_funding_time_ms"] = nft
            row["next_funding_label"] = _fmt_ts_ms(nft)
        except (TypeError, ValueError):
            pass

    if isinstance(oij, dict):
        oi = _parse_f(oij.get("openInterest"))
        row["open_interest_contracts"] = oi
        mp = row["mark_price"]
        if oi is not None and mp is not None and mp > 0:
            row["open_interest_usd_est"] = round(oi * mp, 2)

    tr = _first_row_list(tkj)
    if tr:
        row["taker_buy_sell_ratio_5m"] = _parse_f(tr.get("buySellRatio"))

    gr = _first_row_list(glj)
    if gr:
        row["long_short_account_ratio_5m"] = _parse_f(gr.get("longShortRatio"))

    return row


async def _fetch_whale_alert(client: httpx.AsyncClient) -> dict[str, Any]:
    key = os.getenv("WHALE_ALERT_API_KEY", "").strip()
    out: dict[str, Any] = {"configured": bool(key), "items": [], "note": None}
    if not key:
        return out
    try:
        r = await client.get(
            WHALE_ALERT_URL,
            params={"api_key": key, "min_value": 500_000, "limit": 8},
            timeout=14.0,
        )
        if r.status_code != 200:
            out["note"] = f"Whale Alert returned HTTP {r.status_code}."
            return out
        body = r.json() or {}
        txs = body.get("transactions") if isinstance(body, dict) else None
        if not isinstance(txs, list):
            return out
        items: list[dict[str, Any]] = []
        for tx in txs[:12]:
            if not isinstance(tx, dict):
                continue
            bc = str(tx.get("blockchain") or "").strip()
            h = str(tx.get("hash") or "").strip()
            sym = str(tx.get("symbol") or "").strip().upper()
            amt_usd = _parse_f(tx.get("amount_usd"))
            ts = tx.get("timestamp")
            tlabel = None
            try:
                tlabel = datetime.fromtimestamp(int(ts), tz=UTC).strftime("%Y-%m-%d %H:%MZ")
            except (TypeError, ValueError, OSError):
                pass
            items.append(
                {
                    "blockchain": bc,
                    "symbol": sym,
                    "amount_usd": amt_usd,
                    "timestamp_label": tlabel,
                    "hash": h[:20] + ("…" if len(h) > 20 else ""),
                    "hash_full": h,
                    "explorer": _explorer_tx_url(bc, h),
                }
            )
        out["items"] = items
    except Exception as e:
        out["note"] = f"Whale Alert error: {e!s}"
    return out


async def fetch_onchain_markets_json(ids_csv: str | None = None) -> dict[str, Any]:
    """
    Per-watch Binance futures metrics + optional whale transfers.
    Cached (ONCHAIN_CACHE_SECONDS) in-memory and optionally Redis.
    """
    ids = _ids_for_query(ids_csv)
    pairs = _pairs_in_order(ids)
    bucket = ",".join(p[0] for p in pairs) or "default"
    now = time.time()

    redis_key = _ONCHAIN_REDIS_PREFIX + bucket
    cached = await cache_get_json(redis_key)
    if isinstance(cached, dict) and cached.get("items") is not None:
        return cached

    ent = _memory.get(bucket)
    if isinstance(ent, dict) and (now - float(ent.get("ts") or 0.0)) < _ONCHAIN_TTL:
        return ent["data"]  # type: ignore[return-value]

    fetched_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    disclaimer = (
        "Funding rate, open interest, and 5m taker / long-short account ratios are from Binance "
        "USDT-M futures (public REST). They describe derivatives positioning, not provable on-chain "
        "exchange netflow. Optional whale rows use Whale Alert when configured."
    )

    if not pairs:
        out = {
            "fetched_at": fetched_at,
            "disclaimer": disclaimer,
            "items": [],
            "whales": {"configured": False, "items": [], "note": None},
        }
        _memory[bucket] = {"ts": now, "data": out}
        _evict_memory()
        await cache_set_json(redis_key, out, int(_ONCHAIN_TTL) + 5)
        return out

    async with httpx.AsyncClient(headers=_HEADERS) as client:
        sym_rows = await asyncio.gather(
            *[_fetch_binance_symbol(client, cid, sym, bsym) for cid, sym, bsym in pairs]
        )
        whales = await _fetch_whale_alert(client)

    out = {
        "fetched_at": fetched_at,
        "disclaimer": disclaimer,
        "items": list(sym_rows),
        "whales": whales,
    }
    _memory[bucket] = {"ts": now, "data": out}
    _evict_memory()
    await cache_set_json(redis_key, out, int(_ONCHAIN_TTL) + 5)
    return out
