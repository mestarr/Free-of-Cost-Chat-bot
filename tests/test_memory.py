"""Vector memory helpers (no embedding model load)."""

from backend.memory import format_memory_context, resolve_memory_user_id, sanitize_memory_user_id


def test_sanitize_memory_user_id():
    assert sanitize_memory_user_id("u_abc12345") == "u_abc12345"
    assert sanitize_memory_user_id("short") is None
    assert sanitize_memory_user_id("bad id!") is None


def test_resolve_priority():
    assert (
        resolve_memory_user_id(
            body_user_id="user_body12",
            header_user_id="user_head12",
            api_key_id="kid",
        )
        == "user_body12"
    )
    assert (
        resolve_memory_user_id(
            body_user_id=None,
            header_user_id="user_head12",
            api_key_id="abc",
        )
        == "user_head12"
    )


def test_format_memory_context():
    block = format_memory_context(
        [{"created_at": "2026-01-01T00:00:00Z", "content": "[user] hello"}]
    )
    assert "past chats" in block.lower()
    assert "hello" in block

