"""Macro radar window filtering and parsers."""

from datetime import UTC, datetime, timedelta

from backend.macro_radar import (
    _parse_month_day_year,
    _parse_sec_events,
    _parse_time_ampm,
    filter_events_in_window,
)


def test_filter_events_in_window():
    now = datetime(2026, 5, 20, 12, 0, tzinfo=UTC)
    inside = {
        "id": "a",
        "at_utc": (now + timedelta(hours=20)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    outside = {
        "id": "b",
        "at_utc": (now + timedelta(hours=72)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    got = filter_events_in_window([inside, outside], now=now, window_hours=48)
    assert len(got) == 1
    assert got[0]["id"] == "a"
    assert got[0]["urgency"] == "high"


def test_parse_cpi_date_time():
    assert _parse_month_day_year("Jun. 10, 2026") == (2026, 6, 10)
    assert _parse_time_ampm("08:30 AM") == (8, 30)


def test_parse_sec_events_snippet():
    html = """
May 29 11:00 AM ET
SEC Meetings and Other Events
### Sample Rule Hearing
Some body text.
"""
    events = _parse_sec_events(html)
    assert len(events) >= 1
    assert events[0]["kind"] == "sec"
