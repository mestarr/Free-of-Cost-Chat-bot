"""SQLite-backed API keys and daily usage (optional SaaS-style auth)."""
from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

_lock = threading.Lock()

PEPPER = os.getenv("CCP_KEY_PEPPER", "ccp-dev-pepper-change-in-prod").encode()


def _db_file() -> str:
    raw = os.getenv("CCP_ACCOUNTS_DB", "").strip()
    if raw:
        return raw
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data = Path(root) / ".data"
    data.mkdir(parents=True, exist_ok=True)
    return str(data / "ccp_accounts.sqlite")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_file(), timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def init_db() -> None:
    with _lock:
        conn = _connect()
        try:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS api_keys (
                    id TEXT PRIMARY KEY,
                    key_hash TEXT NOT NULL UNIQUE,
                    label TEXT,
                    created_at TEXT NOT NULL,
                    revoked INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS usage_daily (
                    api_key_id TEXT NOT NULL,
                    day TEXT NOT NULL,
                    requests INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (api_key_id, day)
                );
                """
            )
            conn.commit()
        finally:
            conn.close()


def _hash_secret(raw: str) -> str:
    return hashlib.sha256(PEPPER + raw.strip().encode("utf-8")).hexdigest()


def create_api_key(label: str = "") -> tuple[str, str]:
    """Returns (key_id, plaintext_secret) — show plaintext once."""
    kid = secrets.token_hex(8)
    raw = "ccp_sk_" + secrets.token_urlsafe(24)
    h = _hash_secret(raw)
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                "INSERT INTO api_keys (id, key_hash, label, created_at, revoked) VALUES (?, ?, ?, ?, 0)",
                (kid, h, (label or "").strip()[:200], now),
            )
            conn.commit()
        finally:
            conn.close()
    return kid, raw


def verify_api_key(plaintext: str) -> str | None:
    """Return key id if valid and not revoked."""
    p = (plaintext or "").strip()
    if not p.startswith("ccp_sk_") or len(p) < 16:
        return None
    h = _hash_secret(p)
    with _lock:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT id FROM api_keys WHERE key_hash = ? AND revoked = 0 LIMIT 1",
                (h,),
            ).fetchone()
        finally:
            conn.close()
    return str(row["id"]) if row else None


def record_request(api_key_id: str) -> None:
    day = time.strftime("%Y-%m-%d", time.gmtime())
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                "INSERT INTO usage_daily (api_key_id, day, requests) VALUES (?, ?, 1) "
                "ON CONFLICT(api_key_id, day) DO UPDATE SET requests = requests + 1",
                (api_key_id, day),
            )
            conn.commit()
        finally:
            conn.close()


def usage_summary(api_key_id: str, last_days: int = 14) -> dict[str, Any]:
    last_days = max(1, min(90, last_days))
    cutoff = time.strftime("%Y-%m-%d", time.gmtime(time.time() - last_days * 86400))
    with _lock:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT day, requests FROM usage_daily WHERE api_key_id = ? AND day >= ? ORDER BY day DESC",
                (api_key_id, cutoff),
            ).fetchall()
            meta = conn.execute(
                "SELECT id, label, created_at, revoked FROM api_keys WHERE id = ?",
                (api_key_id,),
            ).fetchone()
        finally:
            conn.close()
    by_day = {str(r["day"]): int(r["requests"]) for r in rows}
    return {
        "key_id": api_key_id,
        "label": str(meta["label"]) if meta else None,
        "created_at": str(meta["created_at"]) if meta else None,
        "revoked": bool(meta["revoked"]) if meta else None,
        "by_day": by_day,
    }
