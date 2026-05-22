"""
Per-user vector memory (RAG): sqlite-vec + sentence-transformers.
Stores chat turns and retrieves relevant snippets for new requests.
"""
from __future__ import annotations

import logging
import os
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
_DEFAULT_DB = os.path.join(_ROOT, ".data", "ccp_memory.sqlite")

_enabled_raw = os.getenv("CCP_MEMORY_ENABLED", "1").strip().lower()
MEMORY_ENABLED = _enabled_raw not in ("0", "false", "no", "off")
MEMORY_DB_PATH = os.getenv("CCP_MEMORY_DB", _DEFAULT_DB).strip() or _DEFAULT_DB
MEMORY_MODEL = os.getenv("CCP_MEMORY_MODEL", "sentence-transformers/all-MiniLM-L6-v2").strip()
_top_k_raw = os.getenv("CCP_MEMORY_TOP_K", "6").strip()
try:
    MEMORY_TOP_K = max(1, min(20, int(_top_k_raw)))
except ValueError:
    MEMORY_TOP_K = 6
_max_chars_raw = os.getenv("CCP_MEMORY_MAX_CHUNK_CHARS", "1200").strip()
try:
    MEMORY_MAX_CHUNK_CHARS = max(200, min(8000, int(_max_chars_raw)))
except ValueError:
    MEMORY_MAX_CHUNK_CHARS = 1200
_dist_raw = os.getenv("CCP_MEMORY_MAX_DISTANCE", "1.05").strip()
try:
    MEMORY_MAX_DISTANCE = max(0.05, min(2.0, float(_dist_raw)))
except ValueError:
    MEMORY_MAX_DISTANCE = 1.05

_EMBED_DIM = 384
_USER_RE = re.compile(r"^[a-zA-Z0-9_-]{8,64}$")

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None
_model: Any = None
_init_error: str | None = None
_deps_ok: bool | None = None


def _check_deps() -> bool:
    global _deps_ok, _init_error
    if _deps_ok is not None:
        return _deps_ok
    try:
        import sqlite_vec  # noqa: F401
        from sentence_transformers import SentenceTransformer  # noqa: F401

        _deps_ok = True
    except ImportError as e:
        _deps_ok = False
        _init_error = str(e)
    return _deps_ok


def memory_status() -> dict[str, Any]:
    ok = MEMORY_ENABLED and _check_deps()
    return {
        "enabled": MEMORY_ENABLED,
        "available": ok,
        "model": MEMORY_MODEL if ok else None,
        "db_path": MEMORY_DB_PATH if ok else None,
        "top_k": MEMORY_TOP_K,
        "error": None if ok else (_init_error or "disabled"),
    }


def sanitize_memory_user_id(raw: str | None) -> str | None:
    if not raw or not str(raw).strip():
        return None
    s = str(raw).strip()
    if len(s) < 8 or len(s) > 64:
        return None
    if not _USER_RE.match(s):
        return None
    return s


def resolve_memory_user_id(
    *,
    body_user_id: str | None,
    header_user_id: str | None,
    api_key_id: str | None,
) -> str | None:
    for candidate in (body_user_id, header_user_id):
        uid = sanitize_memory_user_id(candidate)
        if uid:
            return uid
    if api_key_id:
        safe = re.sub(r"[^a-zA-Z0-9_-]", "", api_key_id)[:48]
        if len(safe) >= 8:
            return f"key_{safe}"
    return None


def _get_model():
    global _model
    if _model is not None:
        return _model
    from sentence_transformers import SentenceTransformer

    _log.info("Loading memory embedding model %s (first request may be slow)…", MEMORY_MODEL)
    _model = SentenceTransformer(MEMORY_MODEL)
    return _model


def _embed_text(text: str) -> bytes:
    import numpy as np
    from sqlite_vec import serialize_float32

    model = _get_model()
    vec = model.encode([text], normalize_embeddings=True)
    arr = np.asarray(vec[0], dtype=np.float32)
    return serialize_float32(arr.tolist())


def _connect() -> sqlite3.Connection:
    global _conn
    if _conn is not None:
        return _conn
    import sqlite_vec

    path = Path(MEMORY_DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(path), check_same_thread=False)
    db.execute("PRAGMA journal_mode=WAL")
    db.enable_load_extension(True)
    sqlite_vec.load(db)
    db.enable_load_extension(False)
    db.execute(
        f"""
        CREATE VIRTUAL TABLE IF NOT EXISTS memory_vec USING vec0(
          user_id TEXT PARTITION KEY,
          embedding float[{_EMBED_DIM}],
          +content TEXT,
          +role TEXT,
          +created_at TEXT
        );
        """
    )
    db.commit()
    _conn = db
    return db


def init_memory_db() -> None:
    if not MEMORY_ENABLED or not _check_deps():
        return
    with _lock:
        _connect()


def _chunk_text(role: str, text: str) -> str:
    body = (text or "").strip()
    if not body:
        return ""
    cap = MEMORY_MAX_CHUNK_CHARS
    if len(body) > cap:
        body = body[:cap] + "…"
    return f"[{role}] {body}"


def ingest_turn(user_id: str, user_text: str, assistant_text: str) -> int:
    if not MEMORY_ENABLED or not _check_deps():
        return 0
    uid = sanitize_memory_user_id(user_id)
    if not uid:
        return 0
    stored = 0
    now = time.time()
    created = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
    with _lock:
        db = _connect()
        for role, raw in (("user", user_text), ("assistant", assistant_text)):
            chunk = _chunk_text(role, raw)
            if len(chunk) < 24:
                continue
            emb = _embed_text(chunk)
            db.execute(
                """
                INSERT INTO memory_vec(user_id, embedding, content, role, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (uid, emb, chunk, role, created),
            )
            stored += 1
        db.commit()
    return stored


def search_memory(user_id: str, query_text: str, *, top_k: int | None = None) -> list[dict[str, Any]]:
    if not MEMORY_ENABLED or not _check_deps():
        return []
    uid = sanitize_memory_user_id(user_id)
    if not uid or not (query_text or "").strip():
        return []
    k = top_k or MEMORY_TOP_K
    q = (query_text or "").strip()[:4000]
    if len(q) < 8:
        return []
    with _lock:
        db = _connect()
        emb = _embed_text(q)
        rows = db.execute(
            f"""
            SELECT rowid, content, role, created_at, distance
            FROM memory_vec
            WHERE embedding MATCH ?
              AND k = {int(k)}
              AND user_id = ?
            ORDER BY distance
            """,
            (emb, uid),
        ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        dist = float(row[4])
        if dist > MEMORY_MAX_DISTANCE:
            continue
        out.append(
            {
                "id": row[0],
                "role": row[1],
                "content": row[2],
                "created_at": row[3],
                "distance": round(dist, 4),
            }
        )
    return out


def format_memory_context(hits: list[dict[str, Any]]) -> str:
    if not hits:
        return ""
    lines = [
        "Relevant memory from this user's past chats (continuity only; may be outdated — prefer live injected data for prices/news):",
    ]
    for h in hits:
        ts = h.get("created_at") or ""
        lines.append(f"- ({ts}) {h.get('content', '')}")
    return "\n".join(lines)


def retrieve_context_block(user_id: str | None, query_text: str) -> str:
    if not user_id:
        return ""
    return format_memory_context(search_memory(user_id, query_text))


def clear_user_memory(user_id: str) -> int:
    uid = sanitize_memory_user_id(user_id)
    if not uid or not MEMORY_ENABLED or not _check_deps():
        return 0
    with _lock:
        db = _connect()
        cur = db.execute("DELETE FROM memory_vec WHERE user_id = ?", (uid,))
        db.commit()
        return int(cur.rowcount or 0)


def count_user_chunks(user_id: str) -> int:
    uid = sanitize_memory_user_id(user_id)
    if not uid or not MEMORY_ENABLED or not _check_deps():
        return 0
    with _lock:
        db = _connect()
        row = db.execute("SELECT COUNT(*) FROM memory_vec WHERE user_id = ?", (uid,)).fetchone()
        return int(row[0]) if row else 0
