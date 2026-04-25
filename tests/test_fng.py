import pytest
from fastapi.testclient import TestClient

import backend.main as main


@pytest.fixture
def fng_stub(monkeypatch):
    async def _fake():
        return {
            "value": 55,
            "classification": "Neutral",
            "updated_at": "2026-01-15T12:00:00Z",
            "next_update_in_seconds": 3600,
            "source": "alternative.me Crypto Fear & Greed Index",
        }

    monkeypatch.setattr(main, "fetch_fear_greed_json", _fake)


def test_fear_greed_endpoint_ok(fng_stub):
    client = TestClient(main.app)
    r = client.get("/api/markets/fear-greed")
    assert r.status_code == 200
    data = r.json()
    assert data["value"] == 55
    assert data["classification"] == "Neutral"
    assert "updated_at" in data
