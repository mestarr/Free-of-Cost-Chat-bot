"""In-process counters and helpers for request logging (thread-safe)."""
from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from collections.abc import Callable
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

_log = logging.getLogger("cryptochatpal")

_lock = threading.Lock()
_counters: dict[str, int] = {
    "http_requests": 0,
    "http_errors": 0,
    "http_latency_ms_sum": 0,
    "price_cache_hit": 0,
    "price_cache_miss": 0,
    "news_cache_hit": 0,
    "news_cache_miss": 0,
}


def inc_counter(key: str, delta: int = 1) -> None:
    with _lock:
        _counters[key] = _counters.get(key, 0) + delta


def add_latency_ms(ms: float) -> None:
    with _lock:
        _counters["http_latency_ms_sum"] = _counters.get("http_latency_ms_sum", 0) + int(ms)


def counters_snapshot() -> dict[str, int]:
    with _lock:
        return dict(_counters)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Assign X-Request-ID, log structured JSON per request, count latency and errors."""

    async def dispatch(self, request: Request, call_next: Callable[[Request], Any]) -> Response:
        rid = request.headers.get("x-request-id") or str(uuid.uuid4())
        request.state.request_id = rid
        t0 = time.perf_counter()
        inc_counter("http_requests")
        try:
            response = await call_next(request)
        except Exception:
            inc_counter("http_errors")
            raise
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        add_latency_ms(elapsed_ms)
        if response.status_code >= 500:
            inc_counter("http_errors")
        response.headers["X-Request-ID"] = rid
        rec = {
            "msg": "http_request",
            "request_id": rid,
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "latency_ms": round(elapsed_ms, 2),
        }
        _log.info(json.dumps(rec, ensure_ascii=False))
        return response
