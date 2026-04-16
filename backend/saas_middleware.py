"""Optional API-key auth + per-key / per-IP rate limits (Redis or in-process)."""
from __future__ import annotations

import asyncio
import os
import time
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .accounts import record_request, verify_api_key
from .redis_cache import REDIS_URL, rate_limit_fixed_window


def _auth_mode() -> str:
    return os.getenv("CCP_AUTH_MODE", "off").strip().lower()


def _rl_limit_key() -> int:
    try:
        return max(5, min(10_000, int(os.getenv("CCP_RATE_LIMIT_PER_KEY", "60"))))
    except ValueError:
        return 60


def _rl_limit_anon() -> int:
    try:
        return max(10, min(50_000, int(os.getenv("CCP_RATE_LIMIT_ANON_IP", "120"))))
    except ValueError:
        return 120


def _rl_window() -> int:
    try:
        return max(10, min(600, int(os.getenv("CCP_RATE_LIMIT_WINDOW_SEC", "60"))))
    except ValueError:
        return 60


def _path_api(path: str) -> bool:
    return path.startswith("/api/")


def _auth_exempt(path: str) -> bool:
    if path in ("/api/health", "/api/metrics"):
        return True
    if path.startswith("/api/admin"):
        return True
    if path.startswith("/docs") or path.startswith("/redoc") or path.startswith("/openapi.json"):
        return True
    return False


def _rate_exempt(path: str) -> bool:
    return _auth_exempt(path)


def _usage_count(path: str) -> bool:
    if path in ("/api/health", "/api/metrics"):
        return False
    if path.startswith("/api/admin"):
        return False
    return True


def extract_api_token(request: Request) -> str:
    h = request.headers.get("x-ccp-api-key") or request.headers.get("X-CCP-API-Key")
    if h and str(h).strip():
        return str(h).strip()
    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    if auth and str(auth).lower().startswith("bearer "):
        return str(auth)[7:].strip()
    return ""


_mem_lock = asyncio.Lock()
_mem_counts: dict[str, int] = {}
_mem_bucket: dict[str, int] = {}


async def _memory_rate_limit(redis_key: str, limit: int, window: int) -> bool:
    async with _mem_lock:
        b = int(time.time() // window)
        prev_b = _mem_bucket.get(redis_key, -1)
        if prev_b != b:
            _mem_counts[redis_key] = 0
            _mem_bucket[redis_key] = b
        n = _mem_counts.get(redis_key, 0) + 1
        _mem_counts[redis_key] = n
        return n <= limit


async def _rate_allow(request: Request) -> bool:
    window = _rl_window()
    kid = getattr(request.state, "ccp_api_key_id", None)
    if kid:
        key = f"k:{kid}"
        limit = _rl_limit_key()
    else:
        ip = getattr(request.state, "ccp_client_ip", "") or "unknown"
        key = f"ip:{ip}"
        limit = _rl_limit_anon()
    if REDIS_URL:
        return await rate_limit_fixed_window(key, limit, window)
    return await _memory_rate_limit(key, limit, window)


class TenantMiddleware(BaseHTTPMiddleware):
    """Sets request.state.ccp_api_key_id; enforces CCP_AUTH_MODE; Redis/memory rate limits."""

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        path = request.url.path
        request.state.ccp_api_key_id = None
        request.state.ccp_client_ip = request.client.host if request.client else ""

        if not _path_api(path):
            return await call_next(request)

        mode = _auth_mode()
        if not _auth_exempt(path):
            token = extract_api_token(request)
            if token:
                kid = verify_api_key(token)
                if kid:
                    request.state.ccp_api_key_id = kid
                elif mode == "required":
                    return JSONResponse(
                        status_code=401,
                        content={"detail": "Invalid API key"},
                    )
            elif mode == "required":
                return JSONResponse(
                    status_code=401,
                    content={
                        "detail": "Missing API key. Send X-CCP-API-Key or Authorization: Bearer <ccp_sk_…>",
                    },
                )

        if not _rate_exempt(path):
            if not await _rate_allow(request):
                return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded"})

        response = await call_next(request)
        kid = getattr(request.state, "ccp_api_key_id", None)
        if kid and _usage_count(path) and response.status_code < 500:
            try:
                record_request(kid)
            except Exception:
                pass
        return response
