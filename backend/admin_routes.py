"""Admin (bootstrap API keys) and per-key usage — gated by CCP_ADMIN_SECRET."""
from __future__ import annotations

import os
from typing import Annotated

from fastapi import APIRouter, Body, HTTPException, Request
from pydantic import BaseModel, Field

from .accounts import create_api_key, usage_summary, verify_api_key
from .saas_middleware import extract_api_token

router = APIRouter(prefix="/api/admin", tags=["admin"])
me_router = APIRouter(prefix="/api/me", tags=["me"])


def _admin_ok(request: Request) -> bool:
    sec = os.getenv("CCP_ADMIN_SECRET", "").strip()
    if not sec:
        return False
    got = request.headers.get("x-ccp-admin-secret") or request.headers.get("X-CCP-Admin-Secret") or ""
    return got.strip() == sec


class CreateKeyBody(BaseModel):
    label: str = Field(default="", max_length=200)


@router.post("/keys")
async def admin_create_key(
    request: Request,
    body: Annotated[CreateKeyBody | None, Body()] = None,
):
    """
    Create a new API key. Requires `X-CCP-Admin-Secret` matching env `CCP_ADMIN_SECRET`.
    Returns the secret once; store it securely.
    """
    if not _admin_ok(request):
        raise HTTPException(status_code=401, detail="Invalid or missing admin secret (X-CCP-Admin-Secret)")
    label = (body.label if body else "") or ""
    kid, raw = create_api_key(label=label)
    return {"id": kid, "api_key": raw, "label": label, "note": "Save api_key now; it is not stored in plaintext."}


@me_router.get("/usage")
async def me_usage(request: Request, days: int = 14):
    """Daily request counts for the caller's API key (same headers as auth)."""
    token = extract_api_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Send X-CCP-API-Key or Authorization: Bearer with your key")
    kid = verify_api_key(token)
    if not kid:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return usage_summary(kid, last_days=days)
