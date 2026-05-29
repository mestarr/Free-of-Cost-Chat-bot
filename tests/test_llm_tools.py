"""LLM tool executors (agent toolkit)."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from backend.llm_tools import (
    GROQ_AGENT_TOOLS,
    GROQ_TOOLS,
    execute_tool,
    groq_tools_for_mode,
    _slim_onchain_tool_payload,
)


def test_groq_agent_tools_superset():
    names = {t["function"]["name"] for t in GROQ_TOOLS}
    agent_names = {t["function"]["name"] for t in GROQ_AGENT_TOOLS}
    assert names <= agent_names
    assert "get_fear_greed" in agent_names
    assert "get_onchain_derivatives" in agent_names


def test_groq_tools_for_mode():
    assert len(groq_tools_for_mode(False)) == len(GROQ_TOOLS)
    assert len(groq_tools_for_mode(True)) == len(GROQ_AGENT_TOOLS)


def test_slim_onchain_tool_payload():
    raw = {
        "fetched_at": "2026-01-01T00:00:00Z",
        "disclaimer": "test",
        "items": [
            {
                "id": "bitcoin",
                "sym": "BTC",
                "mark_price": 70000.0,
                "funding_pct_per_interval": 0.01,
                "open_interest_usd_est": 1e9,
                "taker_buy_sell_ratio_5m": 1.1,
                "long_short_account_ratio_5m": 1.2,
                "extra": "dropped",
            }
        ],
        "whales": {"configured": True, "items": [{"blockchain": "bitcoin", "symbol": "BTC", "amount_usd": 1e7}]},
    }
    slim = _slim_onchain_tool_payload(raw)
    assert slim["items"][0]["id"] == "bitcoin"
    assert "extra" not in slim["items"][0]
    assert slim["whale_transfers"][0]["amount_usd"] == 1e7


@pytest.mark.asyncio
async def test_execute_get_fear_greed():
    fake = {"value": 42, "classification": "Fear"}
    with patch("backend.llm_tools.fetch_fear_greed_json", new_callable=AsyncMock, return_value=fake):
        out = await execute_tool("get_fear_greed", "{}")
    assert json.loads(out)["value"] == 42


@pytest.mark.asyncio
async def test_execute_get_onchain_derivatives():
    fake = {
        "fetched_at": "t",
        "disclaimer": "d",
        "items": [{"id": "ethereum", "sym": "ETH", "mark_price": 3000}],
        "whales": {"configured": False, "items": []},
    }
    with patch("backend.llm_tools.fetch_onchain_markets_json", new_callable=AsyncMock, return_value=fake):
        out = await execute_tool("get_onchain_derivatives", '{"coin_gecko_ids":"ethereum"}')
    parsed = json.loads(out)
    assert parsed["items"][0]["id"] == "ethereum"
