"""
OpenAI-compatible tool definitions and executors for Groq chat completions.
Used to fetch fresh prices/headlines/macro data and to record structured trade analysis.
"""
from __future__ import annotations

import json
import re
from typing import Any

from .news import get_fed_news_api_payload, get_news_items
from .prices import fetch_oil_prices_json, get_price_data


def _normalize_key_risks_field(value: Any) -> list[str]:
    """Models often send a paragraph or JSON string instead of a JSON array — normalize to string list."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()][:12]
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return []
        if s.startswith("["):
            try:
                j = json.loads(s)
                if isinstance(j, list):
                    return [str(x).strip() for x in j if str(x).strip()][:12]
            except json.JSONDecodeError:
                pass
        parts = re.split(r"[\n;|]+", s)
        out = [p.strip().lstrip("•-* ") for p in parts if p.strip()]
        return out[:12]
    return [str(value).strip()] if str(value).strip() else []


def normalize_trade_card(raw: dict | None) -> dict | None:
    """Coerce string/float score fields to ints; key_risks to list (models often emit strings vs arrays)."""
    if not raw or not isinstance(raw, dict):
        return raw
    out = dict(raw)
    int_keys = ("confidence", "score_total", "score_trend", "score_news", "score_rr", "score_regime")
    for k in int_keys:
        v = out.get(k)
        if v is None or isinstance(v, bool):
            continue
        if isinstance(v, int):
            continue
        if isinstance(v, float):
            out[k] = int(round(v))
            continue
        if isinstance(v, str):
            s = v.strip()
            if not s:
                continue
            try:
                out[k] = int(float(s))
            except ValueError:
                pass
    if "key_risks" in out:
        out["key_risks"] = _normalize_key_risks_field(out.get("key_risks"))
    return out


GROQ_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_prices",
            "description": (
                "Fetch live USD spot prices and 24h change from CoinGecko. "
                "Use when the user asks about specific coins not clearly covered in the initial snapshot, "
                "or when you need to double-check numbers. Coin ids are lowercase slugs (e.g. bitcoin, ethereum)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "coin_gecko_ids": {
                        "type": "string",
                        "description": (
                            "Comma-separated CoinGecko coin ids, e.g. bitcoin,ethereum,solana. "
                            "If omitted or empty, uses the app default watchlist."
                        ),
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_crypto_headlines",
            "description": (
                "Fetch recent deduped crypto RSS headlines (CoinDesk, Decrypt, BeInCrypto when reachable) as JSON. "
                "Use when the user asks for latest news beyond the injected headline block or wants more items."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "max_items": {
                        "type": "string",
                        "description": "Max headlines as digits 1-25 (e.g. 14). Omit for 14.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_macro_snapshot",
            "description": (
                "Fetch a compact macro bundle: delayed oil/metals benchmarks (WTI, Brent, gold, silver) "
                "plus Fed-related RSS headlines (rate cuts / policy easing themes). "
                "Use for macro, rates, risk-off, or commodity context."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "emit_trade_analysis",
            "description": (
                "Record a structured trading / investment action view. "
                "Call once when the user asks for buy/sell/hold, positioning, trade plan, scorecard, or full analysis. "
                "Do NOT call this tool when the user only constrains format (e.g. yes/no, one word, A or B only, "
                "single sentence) without asking for structured trade output — answer in plain text only. "
                "After calling, still write a clear natural-language answer for the user in their language. "
                "For confidence and score_* use string digits only (e.g. \"62\"). "
                "For key_risks use one string with risks separated by semicolons or newlines (not a JSON array)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "view": {
                        "type": "string",
                        "description": "e.g. Buy bias, Sell bias, Hold, Neutral / Wait, No trade / Wait",
                    },
                    "confidence": {
                        "type": "string",
                        "description": 'Confidence 0-100 as digits in a string, e.g. "65"',
                    },
                    "score_total": {
                        "type": "string",
                        "description": 'Sum 0-100 as string digits, e.g. "72"',
                    },
                    "score_trend": {
                        "type": "string",
                        "description": 'Trend/momentum bucket 0-25 as string digits, e.g. "18"',
                    },
                    "score_news": {
                        "type": "string",
                        "description": 'News/macro bucket 0-25 as string digits',
                    },
                    "score_rr": {
                        "type": "string",
                        "description": 'Risk-reward bucket 0-25 as string digits',
                    },
                    "score_regime": {
                        "type": "string",
                        "description": 'Regime/volatility bucket 0-25 as string digits',
                    },
                    "timeframe": {
                        "type": "string",
                        "description": "e.g. intraday, swing, long-term — or your assumption",
                    },
                    "thesis": {"type": "string", "description": "1-2 line thesis"},
                    "key_risks": {
                        "type": "string",
                        "description": (
                            "Two or more risks in one string separated by semicolons or newlines "
                            '(e.g. "Regulatory risk; Volatility below 65k support") — not a JSON array.'
                        ),
                    },
                    "what_changes_view": {
                        "type": "string",
                        "description": "One line on what would flip the view",
                    },
                },
                "required": ["view", "confidence"],
            },
        },
    },
]


async def execute_tool(name: str, arguments_json: str) -> str:
    """Run a tool by name; return a JSON string for the chat `tool` message content."""
    try:
        args = json.loads(arguments_json) if (arguments_json or "").strip() else {}
    except json.JSONDecodeError:
        args = {}

    if name == "get_prices":
        raw = args.get("coin_gecko_ids")
        ids = raw.strip() if isinstance(raw, str) else ""
        data = await get_price_data(ids if ids else None)
        return json.dumps(
            {
                "coin_gecko_usd": data,
                "note": "Keys are CoinGecko ids. Each value may include usd and usd_24h_change.",
            },
            ensure_ascii=False,
        )

    if name == "get_crypto_headlines":
        n = args.get("max_items", 14)
        try:
            cap = max(1, min(25, int(float(str(n).strip()))))
        except (TypeError, ValueError):
            cap = 14
        items = await get_news_items()
        slim = []
        for it in items[:cap]:
            slim.append(
                {
                    "source": it.get("source"),
                    "title": it.get("title"),
                    "link": it.get("link"),
                    "sentiment": it.get("sentiment"),
                    "summary": (it.get("summary") or "")[:240],
                }
            )
        return json.dumps({"items": slim, "count": len(slim)}, ensure_ascii=False)

    if name == "get_macro_snapshot":
        oil = await fetch_oil_prices_json()
        fed = await get_fed_news_api_payload(limit=8)
        return json.dumps({"oil_metals": oil, "fed_headlines": fed}, ensure_ascii=False)

    if name == "emit_trade_analysis":
        return json.dumps(
            {
                "status": "recorded",
                "hint": "Now write your user-facing answer; repeat view, confidence, and plan in prose.",
            },
            ensure_ascii=False,
        )

    return json.dumps({"error": f"unknown_tool:{name}"}, ensure_ascii=False)
