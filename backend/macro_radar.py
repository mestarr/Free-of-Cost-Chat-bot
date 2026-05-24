"""
Macro radar: FOMC / CPI / SEC events within a rolling time window (default 48h).
Fetches public .gov schedules (no API keys).
"""
from __future__ import annotations

import os
import re
import time
from datetime import UTC, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

_ET: ZoneInfo | timezone | None = None


def _eastern_tz() -> ZoneInfo | timezone:
    """America/New_York; on Windows install tzdata (see requirements.txt)."""
    global _ET
    if _ET is not None:
        return _ET
    try:
        _ET = ZoneInfo("America/New_York")
    except ZoneInfoNotFoundError:
        _ET = timezone(timedelta(hours=-5))
    return _ET
_USER_AGENT = os.getenv(
    "NEWS_USER_AGENT",
    "Mozilla/5.0 (compatible; CryptoChatPal/1.0; +https://github.com/)",
)

_window_raw = os.getenv("MACRO_RADAR_WINDOW_HOURS", "48").strip()
try:
    MACRO_RADAR_WINDOW_HOURS = max(6, min(168, float(_window_raw)))
except ValueError:
    MACRO_RADAR_WINDOW_HOURS = 48.0

_ttl_raw = os.getenv("MACRO_RADAR_CACHE_SECONDS", "3600").strip()
try:
    MACRO_RADAR_CACHE_SECONDS = max(300, min(86400, float(_ttl_raw)))
except ValueError:
    MACRO_RADAR_CACHE_SECONDS = 3600.0

_cache: dict[str, Any] = {"ts": 0.0, "payload": {}}

_MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}

_FOMC_LINK_DATE = re.compile(r"fomc(?:pressconf|presconf|projtabl)(\d{8})", re.I)
_CPI_ROW = re.compile(
    r"\|\s*([A-Za-z]+\s+\d{4})\s*\|\s*([A-Za-z]+\.\s+\d{1,2},\s*\d{4})\s*\|\s*(\d{2}:\d{2}\s*[AP]M)\s*\|",
    re.I,
)
_SEC_EVENT = re.compile(
    r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
    r"Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"\s+(\d{1,2})\s+(\d{1,2}):(\d{2})\s+(AM|PM)\s+ET",
    re.I,
)


def _et_to_utc(year: int, month: int, day: int, hour: int, minute: int) -> datetime:
    dt = datetime(year, month, day, hour, minute, tzinfo=_eastern_tz())
    return dt.astimezone(UTC)


def _parse_month_day_year(text: str) -> tuple[int, int, int] | None:
    """e.g. May 12, 2026"""
    m = re.match(r"([A-Za-z]+)\.?\s+(\d{1,2}),\s*(\d{4})", (text or "").strip())
    if not m:
        return None
    mon = _MONTHS.get(m.group(1).lower())
    if not mon:
        return None
    return int(m.group(3)), mon, int(m.group(2))


def _parse_time_ampm(text: str) -> tuple[int, int] | None:
    m = re.match(r"(\d{1,2}):(\d{2})\s*(AM|PM)", (text or "").strip(), re.I)
    if not m:
        return None
    h = int(m.group(1)) % 12
    if m.group(3).upper() == "PM":
        h += 12
    return h, int(m.group(2))


def filter_events_in_window(
    events: list[dict[str, Any]],
    *,
    now: datetime | None = None,
    window_hours: float | None = None,
) -> list[dict[str, Any]]:
    """Keep events starting within the next window_hours (and not more than 2h in the past)."""
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    win = window_hours if window_hours is not None else MACRO_RADAR_WINDOW_HOURS
    horizon = now + timedelta(hours=win)
    grace_past = now - timedelta(hours=2)
    out: list[dict[str, Any]] = []
    for ev in events:
        at_s = ev.get("at_utc")
        if not at_s:
            continue
        try:
            at = datetime.fromisoformat(str(at_s).replace("Z", "+00:00"))
        except ValueError:
            continue
        if at.tzinfo is None:
            at = at.replace(tzinfo=UTC)
        if grace_past <= at <= horizon:
            delta = at - now
            hours = max(0.0, delta.total_seconds() / 3600.0)
            row = dict(ev)
            row["hours_until"] = round(hours, 2)
            row["urgency"] = "high" if hours <= 24 else "medium"
            out.append(row)
    out.sort(key=lambda x: (x.get("at_utc") or "", x.get("kind") or ""))
    return out


async def _fetch_fomc_events(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    url = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
    r = await client.get(url, headers={"User-Agent": _USER_AGENT})
    r.raise_for_status()
    html = r.text
    events: list[dict[str, Any]] = []
    seen: set[str] = set()
    for m in _FOMC_LINK_DATE.finditer(html):
        ymd = m.group(1)
        y, mo, d = int(ymd[:4]), int(ymd[4:6]), int(ymd[6:8])
        key = f"fomc-decision-{ymd}"
        if key in seen:
            continue
        seen.add(key)
        at = _et_to_utc(y, mo, d, 14, 0)
        events.append(
            {
                "id": key,
                "kind": "fomc",
                "title": "FOMC rate decision / statement (≈2:00 PM ET)",
                "at_utc": at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "source": "federalreserve.gov",
            }
        )
    year = datetime.now(_eastern_tz()).year
    block_m = re.search(rf"####\s*{year}\s+FOMC Meetings(.*?)(?=####\s*\d{{4}}|\Z)", html, re.S | re.I)
    if block_m:
        block = block_m.group(1)
        month_pat = re.compile(
            r"(January|February|March|April|May|June|July|August|September|October|November|December)"
            r"\s+(\d{1,2})-(\d{1,2})",
            re.I,
        )
        for mm in month_pat.finditer(block):
            mon_name, d1, _d2 = mm.group(1), int(mm.group(2)), int(mm.group(3))
            mon = _MONTHS.get(mon_name.lower())
            if not mon:
                continue
            start_key = f"fomc-start-{year}-{mon:02d}-{d1:02d}"
            if start_key not in seen:
                seen.add(start_key)
                at_start = _et_to_utc(year, mon, d1, 9, 0)
                events.append(
                    {
                        "id": start_key,
                        "kind": "fomc",
                        "title": "FOMC meeting begins (Day 1)",
                        "at_utc": at_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "source": "federalreserve.gov",
                    }
                )
    return events


async def _fetch_cpi_events(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    url = "https://www.bls.gov/schedule/news_release/cpi.htm"
    r = await client.get(url, headers={"User-Agent": _USER_AGENT})
    r.raise_for_status()
    events: list[dict[str, Any]] = []
    for m in _CPI_ROW.finditer(r.text):
        ref_month, rel_date, rel_time = m.group(1), m.group(2), m.group(3)
        parsed = _parse_month_day_year(rel_date)
        tm = _parse_time_ampm(rel_time)
        if not parsed or not tm:
            continue
        y, mo, d = parsed
        h, mi = tm
        at = _et_to_utc(y, mo, d, h, mi)
        events.append(
            {
                "id": f"cpi-{y}-{mo:02d}-{d:02d}",
                "kind": "cpi",
                "title": f"CPI release ({ref_month.strip()})",
                "at_utc": at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "source": "bls.gov",
            }
        )
    return events


def _parse_sec_events(html: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    lines = html.replace("\r\n", "\n").split("\n")
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        tm = _SEC_EVENT.search(line)
        if not tm:
            i += 1
            continue
        mon_s, day_s, hr_s, min_s, ampm = tm.group(1), tm.group(2), tm.group(3), tm.group(4), tm.group(5)
        mon = _MONTHS.get(mon_s.lower())
        if not mon:
            i += 1
            continue
        year = datetime.now(_eastern_tz()).year
        h = int(hr_s) % 12
        if ampm.upper() == "PM":
            h += 12
        at = _et_to_utc(year, mon, int(day_s), h, int(min_s))
        category = ""
        title = ""
        j = i + 1
        while j < len(lines) and j < i + 6:
            s = lines[j].strip()
            if _SEC_EVENT.search(s):
                break
            if s.startswith("###"):
                title = s.lstrip("#").strip()
            elif s and not category and "SEC" in s:
                category = s
            j += 1
        if not title:
            i += 1
            continue
        blob = f"{category} {title}".lower()
        is_meeting = "sec meetings" in blob or "public hearing" in blob
        crypto_adj = any(
            k in blob
            for k in (
                "crypto",
                "digital asset",
                "bitcoin",
                "etf",
                "token",
                "blockchain",
                "enforcement",
                "rule",
                "regulation",
            )
        )
        if not is_meeting and not crypto_adj:
            i += 1
            continue
        eid = f"sec-{year}-{mon:02d}-{int(day_s):02d}-{h:02d}{min_s}"
        events.append(
            {
                "id": eid,
                "kind": "sec",
                "title": title[:180],
                "at_utc": at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "source": "sec.gov",
                "category": category or "SEC event",
            }
        )
        i = j
    return events


async def _fetch_sec_events(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    url = "https://www.sec.gov/news/upcoming-events"
    r = await client.get(url, headers={"User-Agent": _USER_AGENT})
    r.raise_for_status()
    return _parse_sec_events(r.text)


async def collect_macro_events() -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=25.0, follow_redirects=True) as client:
        for fetcher in (_fetch_fomc_events, _fetch_cpi_events, _fetch_sec_events):
            try:
                events.extend(await fetcher(client))
            except Exception:
                continue
    dedup: dict[str, dict[str, Any]] = {}
    for ev in events:
        dedup[ev.get("id") or str(ev)] = ev
    return list(dedup.values())


def format_radar_context(events: list[dict[str, Any]]) -> str:
    if not events:
        return ""
    lines = [
        "Macro radar (official schedules; events in the next "
        f"{int(MACRO_RADAR_WINDOW_HOURS)}h — reduce size / widen stops around these times):"
    ]
    for ev in events:
        kind = str(ev.get("kind", "")).upper()
        title = ev.get("title", "")
        hrs = ev.get("hours_until")
        tail = f"in ~{hrs:.0f}h" if hrs is not None else ""
        lines.append(f"- [{kind}] {title} {tail}".strip())
    return "\n".join(lines)


async def fetch_macro_radar_json() -> dict[str, Any]:
    now = time.time()
    if _cache["payload"] and (now - float(_cache["ts"])) < MACRO_RADAR_CACHE_SECONDS:
        return dict(_cache["payload"])

    all_events = await collect_macro_events()
    active = filter_events_in_window(all_events)
    payload = {
        "fetched_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "window_hours": MACRO_RADAR_WINDOW_HOURS,
        "events": active,
        "count": len(active),
    }
    _cache["ts"] = now
    _cache["payload"] = payload
    return payload
