"""War room message builders."""

from backend.war_room import (
    BEAR_SYSTEM,
    BULL_SYSTEM,
    REFEREE_SYSTEM,
    build_debate_messages,
    build_referee_messages,
    format_stored_assistant_text,
    last_user_text,
)


def test_last_user_text():
    msgs = [
        {"role": "system", "content": "ctx"},
        {"role": "user", "content": "Should I buy ETH?"},
    ]
    assert last_user_text(msgs) == "Should I buy ETH?"


def test_build_debate_messages_includes_persona():
    base = [
        {"role": "system", "content": "prices"},
        {"role": "user", "content": "BTC outlook?"},
    ]
    bull = build_debate_messages(base, "bull")
    assert any(m.get("content") == BULL_SYSTEM for m in bull if m.get("role") == "system")
    bear = build_debate_messages(base, "bear")
    assert any(m.get("content") == BEAR_SYSTEM for m in bear if m.get("role") == "system")


def test_build_referee_messages_includes_debate():
    base = [
        {"role": "system", "content": "ctx"},
        {"role": "user", "content": "Should I DCA into SOL?"},
    ]
    ref = build_referee_messages(base, "Bull says buy.", "Bear says wait.")
    assert any(m.get("content") == REFEREE_SYSTEM for m in ref if m.get("role") == "system")
    last = ref[-1]
    assert last["role"] == "user"
    assert "Bull says buy." in last["content"]
    assert "Bear says wait." in last["content"]
    assert "Should I DCA into SOL?" in last["content"]


def test_format_stored_assistant_text():
    text = format_stored_assistant_text("bull case", "bear case", "final answer")
    assert "bull case" in text
    assert "bear case" in text
    assert "final answer" in text
