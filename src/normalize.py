"""标准化层：统一时间为北京时间，按 URL/标题去重。"""
from __future__ import annotations

import time
from datetime import datetime, timezone, timedelta
from typing import Any

from dateutil import parser as dateparser

BEIJING = timezone(timedelta(hours=8))


def _to_beijing_iso(item: dict[str, Any]) -> str | None:
    """把条目时间转成北京时间 ISO 字符串。解析失败返回 None。"""
    parsed = item.get("published_parsed")
    if parsed:
        # feedparser 给的是 UTC struct_time
        dt = datetime.fromtimestamp(time.mktime(parsed), tz=timezone.utc)
        return dt.astimezone(BEIJING).isoformat()
    raw = item.get("published_raw")
    if raw:
        try:
            dt = dateparser.parse(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(BEIJING).isoformat()
        except (ValueError, OverflowError):
            return None
    return None


def normalize(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """标准化 + 去重。去重键优先用 URL，其次用标题。"""
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    out: list[dict[str, Any]] = []
    for it in items:
        url = it.get("url", "").strip()
        title = it.get("title", "").strip().lower()
        if url and url in seen_urls:
            continue
        if title and title in seen_titles:
            continue
        if url:
            seen_urls.add(url)
        if title:
            seen_titles.add(title)
        it["published_at"] = _to_beijing_iso(it)
        out.append(it)
    return out
