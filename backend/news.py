"""
Headlines from RSS feeds (crypto-focused). Cached to avoid hammering publishers.

Sources (defaults):
- CoinDesk (https://www.coindesk.com/)
- Decrypt (https://decrypt.co/)
- BeInCrypto (https://beincrypto.com/) — may return HTTP 403 from some networks; skipped silently if so.
"""
from __future__ import annotations

import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlparse

import httpx

USER_AGENT = os.getenv(
    "NEWS_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
)

# (label, url, max items per feed)
DEFAULT_FEEDS: list[tuple[str, str, int]] = [
    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/", 14),
    ("Decrypt", "https://decrypt.co/feed", 14),
    ("BeInCrypto", "https://beincrypto.com/feed/", 12),
]

TTL_SECONDS = float(os.getenv("NEWS_CACHE_SECONDS", "300"))
MAX_HEADLINES_LLM = int(os.getenv("NEWS_MAX_HEADLINES_LLM", "18"))

_cache: dict[str, Any] = {"ts": 0.0, "items": [], "fetched_at": ""}

_POS = re.compile(
    r"\b(surge|surges|rally|rallies|gain|gains|rise|rose|risen|jump|jumps|record|high|approve|approved|"
    r"launch|launches|backed|breakthrough|growth|expand|expands|win|wins|soar|soars)\b",
    re.I,
)
_NEG = re.compile(
    r"\b(ban|banned|hack|hacked|fraud|scam|crash|selloff|sell-off|drop|drops|fall|falls|plunge|loss|losses|"
    r"lawsuit|crime|exploit|warning|crisis|layoff|layoffs|cuts|war|attack|death|banned|violation|"
    r"ponzi|charges|arrest|penalty)\b",
    re.I,
)


def _local(tag: str) -> str:
    if tag.startswith("{"):
        return tag.split("}", 1)[1]
    return tag


def _text(el: ET.Element | None) -> str:
    if el is None or el.text is None:
        return ""
    return " ".join(el.text.split())


def _strip_html(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _sentiment(title: str, summary: str) -> str:
    blob = f"{title} {summary}"
    pn = len(_POS.findall(blob))
    nn = len(_NEG.findall(blob))
    if nn > pn:
        return "negative"
    if pn > nn:
        return "positive"
    return "neutral"


def _parse_pub_date(s: str) -> float:
    s = (s or "").strip()
    if not s:
        return 0.0
    try:
        dt = parsedate_to_datetime(s)
        if dt.tzinfo is None:
            return dt.timestamp()
        return dt.timestamp()
    except (TypeError, ValueError, OverflowError):
        pass
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.timestamp()
    except ValueError:
        return 0.0


def _parse_rss(xml_bytes: bytes, source: str) -> list[dict[str, Any]]:
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return []

    out: list[dict[str, Any]] = []
    for item in root.iter():
        if _local(item.tag) != "item":
            continue
        title = link = desc = pub = ""
        for child in item:
            ln = _local(child.tag)
            if ln == "title":
                title = _text(child)
            elif ln == "link":
                link = (_text(child) or (child.get("href") or "")).strip()
            elif ln == "description":
                desc = _strip_html(_text(child))
            elif ln == "pubDate":
                pub = _text(child)
        if not title or not link:
            continue
        summary = desc[:280] + ("…" if len(desc) > 280 else "") if desc else ""
        out.append(
            {
                "source": source,
                "title": title.strip(),
                "link": link.strip(),
                "summary": summary,
                "published": pub.strip(),
                "published_ts": _parse_pub_date(pub),
                "sentiment": _sentiment(title, summary),
            }
        )
    return out


async def _fetch_feed(client: httpx.AsyncClient, source: str, url: str, cap: int) -> list[dict[str, Any]]:
    try:
        r = await client.get(url, headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml, text/xml, */*"})
        if r.status_code != 200:
            return []
        items = _parse_rss(r.content, source)[:cap]
        return items
    except Exception:
        return []


def _norm_link(u: str) -> str:
    try:
        p = urlparse(u)
        return f"{p.scheme}://{p.netloc}{p.path}".rstrip("/").lower()
    except Exception:
        return u.lower()


async def get_news_items() -> list[dict[str, Any]]:
    now = time.time()
    if _cache["items"] and (now - _cache["ts"]) < TTL_SECONDS:
        return _cache["items"]

    merged: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        for source, url, cap in DEFAULT_FEEDS:
            merged.extend(await _fetch_feed(client, source, url, cap))

    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for it in sorted(merged, key=lambda x: x.get("published_ts") or 0, reverse=True):
        key = _norm_link(it["link"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(it)

    _cache["ts"] = now
    _cache["items"] = deduped
    _cache["fetched_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return deduped


async def get_news_api_payload(limit: int = 25) -> dict[str, Any]:
    items = await get_news_items()
    return {
        "fetched_at": _cache.get("fetched_at") or "",
        "items": items[:limit],
    }


async def fetch_news_snapshot_for_llm() -> str:
    """Compact headline list for the model (attribution + links)."""
    items = await get_news_items()
    if not items:
        return ""

    lines: list[str] = [
        "Recent headlines from RSS (CoinDesk, Decrypt, BeInCrypto when reachable). Summarize accurately, name the source for each story, "
        "and do not invent stories. These are not financial advice. Prefer linking users to the article URL.\n"
    ]
    for it in items[:MAX_HEADLINES_LLM]:
        t = it["title"].replace("\n", " ")
        src = it["source"]
        link = it["link"]
        summ = (it.get("summary") or "")[:200]
        if summ:
            lines.append(f"- [{src}] {t} — {summ} — {link}")
        else:
            lines.append(f"- [{src}] {t} — {link}")
    return "\n".join(lines)
