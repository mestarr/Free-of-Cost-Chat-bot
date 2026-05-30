"""
stdio MCP server — expose CryptoChatPal market data tools to Claude Desktop, Cursor, ChatGPT, etc.

Run from project root:
    python -m backend.mcp_server

Do not print to stdout (breaks JSON-RPC); logs go to stderr only.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

_root = Path(__file__).resolve().parent.parent
load_dotenv(_root / ".env")

from .llm_tools import execute_tool  # noqa: E402
from .macro_radar import fetch_macro_radar_json  # noqa: E402

logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(message)s")
_log = logging.getLogger("cryptochatpal.mcp")

mcp = FastMCP(
    "CryptoChatPal",
    instructions=(
        "Crypto market data for AI assistants: CoinGecko spot prices, crypto RSS headlines, "
        "oil/metals + Fed macro bundle, Fear & Greed index, Binance USDT-M funding/OI metrics, "
        "and FOMC/CPI/SEC macro radar. CoinGecko coin ids are lowercase slugs (e.g. bitcoin, ethereum)."
    ),
)


async def _run_tool(name: str, args: dict | None = None) -> str:
    payload = json.dumps(args or {}, ensure_ascii=False)
    _log.info("tool %s args=%s", name, payload[:200])
    return await execute_tool(name, payload)


@mcp.tool()
async def get_prices(coin_gecko_ids: str = "") -> str:
    """Fetch live USD spot prices and 24h percent change from CoinGecko.

    Args:
        coin_gecko_ids: Comma-separated CoinGecko ids (e.g. bitcoin,ethereum). Empty = default watchlist.
    """
    return await _run_tool("get_prices", {"coin_gecko_ids": coin_gecko_ids})


@mcp.tool()
async def get_crypto_headlines(max_items: int = 14) -> str:
    """Fetch recent deduped crypto RSS headlines (CoinDesk, Decrypt, BeInCrypto when reachable).

    Args:
        max_items: Number of headlines, 1–25 (default 14).
    """
    cap = max(1, min(25, int(max_items)))
    return await _run_tool("get_crypto_headlines", {"max_items": str(cap)})


@mcp.tool()
async def get_macro_snapshot() -> str:
    """Fetch oil/metals benchmarks (WTI, Brent, gold, silver) plus Fed-related RSS headlines."""
    return await _run_tool("get_macro_snapshot", {})


@mcp.tool()
async def get_fear_greed() -> str:
    """Fetch the Crypto Fear & Greed Index (0–100) from Alternative.me."""
    return await _run_tool("get_fear_greed", {})


@mcp.tool()
async def get_onchain_derivatives(coin_gecko_ids: str = "") -> str:
    """Binance USDT-M futures: funding, open interest, taker ratio, long/short ratio; optional whales.

    Args:
        coin_gecko_ids: Comma-separated CoinGecko ids. Empty = default watchlist.
    """
    return await _run_tool("get_onchain_derivatives", {"coin_gecko_ids": coin_gecko_ids})


@mcp.tool()
async def get_macro_radar() -> str:
    """Upcoming FOMC, CPI, and SEC events within the configured window (default 48 hours)."""
    data = await fetch_macro_radar_json()
    return json.dumps(data, ensure_ascii=False)


@mcp.resource("cryptochatpal://about")
def about_resource() -> str:
    """Server capabilities and id conventions."""
    return (
        "CryptoChatPal MCP — tools backed by CoinGecko, crypto RSS, Yahoo oil/metals, "
        "Alternative.me Fear & Greed, Binance futures REST, and .gov macro calendars.\n"
        "Coin ids: lowercase CoinGecko slugs (bitcoin, ethereum, solana).\n"
        "Project: https://github.com/your-repo/CryptoChatPal (local server, no API key required for data tools)."
    )


def main() -> None:
    os.chdir(_root)
    mcp.run()


if __name__ == "__main__":
    main()
