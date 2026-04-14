from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)


def test_health_ok():
    r = client.get("/api/health")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert "redis" in data


def test_metrics_json():
    r = client.get("/api/metrics")
    assert r.status_code == 200
    data = r.json()
    assert "counters" in data
    assert "http_requests" in data["counters"]
    assert "http_latency_avg_ms" in data


def test_metrics_prometheus():
    r = client.get("/api/metrics?format=prometheus")
    assert r.status_code == 200
    assert b"ccp_http_requests_total" in r.content


def test_request_id_header():
    r = client.get("/api/health", headers={"X-Request-ID": "custom-id"})
    assert r.status_code == 200
    assert r.headers.get("x-request-id") == "custom-id"
