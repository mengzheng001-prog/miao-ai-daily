"""粗筛层（不调 LLM）：24h 硬时间窗 + 宽松关键词白名单。

目的是减量，把明显无关/过期的剔掉，精筛交给 LLM。详见 references/scoring-and-tags.md。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from dateutil import parser as dateparser

# 宽松白名单：命中任一即保留（粗筛，不是精筛）
KEYWORDS = [
    "ai", "llm", "agent", "rag", "multimodal", "diffusion", "model",
    "gpt", "claude", "gemini", "openai", "anthropic", "deepmind",
    "neural", "transformer", "inference", "fine-tun", "embedding",
    "robot", "machine learning", "deep learning", "人工智能", "大模型", "智能体",
]


def _within_24h(published_at: str | None, now: datetime) -> bool:
    if not published_at:
        # 无时间的条目：保守保留，交给 LLM 判断（也可改为丢弃）
        return True
    try:
        dt = dateparser.parse(published_at)
    except (ValueError, OverflowError):
        return True
    return dt >= now - timedelta(hours=24)


def _keyword_hit(item: dict[str, Any]) -> bool:
    text = f"{item.get('title','')} {item.get('raw_text','')}".lower()
    return any(k in text for k in KEYWORDS)


def prefilter(items: list[dict[str, Any]], now: datetime | None = None) -> list[dict[str, Any]]:
    """返回通过 24h 时间窗 + 关键词粗筛的条目。"""
    from .normalize import BEIJING

    now = now or datetime.now(BEIJING)
    out = []
    for it in items:
        if not _within_24h(it.get("published_at"), now):
            continue
        # 官方源(C)放宽关键词要求：本身就是 AI 机构
        if it.get("category") == "C" or _keyword_hit(it):
            out.append(it)
    return out
