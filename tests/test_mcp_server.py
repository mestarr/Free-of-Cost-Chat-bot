"""MCP server tool wrappers (mocked upstream)."""

import asyncio
import json
from unittest.mock import AsyncMock, patch

from backend import mcp_server


def test_mcp_get_prices():
    fake = json.dumps({"coin_gecko_usd": {"bitcoin": {"usd": 70000}}})
    with patch.object(mcp_server, "execute_tool", new_callable=AsyncMock, return_value=fake):
        out = asyncio.run(mcp_server.get_prices("bitcoin"))
    assert "bitcoin" in out


def test_mcp_get_macro_radar():
    fake = {"events": [], "window_hours": 48}
    with patch.object(mcp_server, "fetch_macro_radar_json", new_callable=AsyncMock, return_value=fake):
        out = asyncio.run(mcp_server.get_macro_radar())
    parsed = json.loads(out)
    assert parsed["window_hours"] == 48


def test_mcp_about_resource():
    text = mcp_server.about_resource()
    assert "CoinGecko" in text
