"""On-chain / Binance futures bundle API (mocked upstream)."""
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)


SAMPLE = {
    "fetched_at": "2026-01-01T12:00:00Z",
    "disclaimer": "test disclaimer",
    "items": [
        {
            "id": "bitcoin",
            "sym": "BTC",
            "binance_symbol": "BTCUSDT",
            "mark_price": 100000.0,
            "index_price": 100000.0,
            "funding_rate": 0.0001,
            "funding_pct_per_interval": 0.01,
            "next_funding_label": "2026-01-01 16:00Z",
            "open_interest_contracts": 100000.0,
            "open_interest_usd_est": 10_000_000_000.0,
            "taker_buy_sell_ratio_5m": 1.05,
            "long_short_account_ratio_5m": 1.12,
        }
    ],
    "whales": {"configured": False, "items": [], "note": None},
}


def test_onchain_endpoint_ok():
    with patch("backend.main.fetch_onchain_markets_json", new_callable=AsyncMock, return_value=SAMPLE):
        r = client.get("/api/markets/onchain?ids=bitcoin")
    assert r.status_code == 200
    data = r.json()
    assert data["fetched_at"] == SAMPLE["fetched_at"]
    assert len(data["items"]) == 1
    assert data["items"][0]["sym"] == "BTC"
    assert data["whales"]["configured"] is False


def test_onchain_endpoint_uses_query_ids():
    async def fake(ids_csv=None):
        return {
            **SAMPLE,
            "items": [
                {
                    "id": "ethereum",
                    "sym": "ETH",
                    "binance_symbol": "ETHUSDT",
                    "funding_pct_per_interval": 0.02,
                }
            ],
        }

    with patch("backend.main.fetch_onchain_markets_json", side_effect=fake):
        r = client.get("/api/markets/onchain?ids=ethereum")
    assert r.status_code == 200
    assert r.json()["items"][0]["id"] == "ethereum"
