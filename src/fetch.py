"""抓取层：读 config/sources.yaml，逐个 RSS 源抓取条目。

MVP 只处理 type=rss 且 enabled=true 的源。type=web 的源留待后续网页抓取实现。
单个源失败要容错：记录并跳过，不影响其他源。
详见技能 references/sources.md。
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any

import feedparser
import yaml

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "sources.yaml"


def load_config() -> dict[str, Any]:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _stable_id(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]


def fetch_source(source: dict[str, Any]) -> list[dict[str, Any]]:
    """抓取单个 RSS 源，返回原始条目列表。失败返回空列表。"""
    name = source.get("name", "?")
    url = source.get("url", "")
    try:
        feed = feedparser.parse(url)
        items: list[dict[str, Any]] = []
        for e in feed.entries:
            link = e.get("link", "")
            if not link:
                continue
            # 尽量取摘要/正文片段喂给 LLM
            raw_text = e.get("summary", "") or e.get("description", "")
            items.append(
                {
                    "id": _stable_id(link),
                    "title": e.get("title", "").strip(),
                    "source": name,
                    "category": source.get("category", ""),
                    "url": link,
                    # 原始时间，normalize 层统一转北京时间
                    "published_raw": e.get("published", "") or e.get("updated", ""),
                    "published_parsed": e.get("published_parsed") or e.get("updated_parsed"),
                    "raw_text": raw_text,
                }
            )
        logger.info("源 [%s] 抓到 %d 条", name, len(items))
        return items
    except Exception as exc:  # 单源容错
        logger.warning("源 [%s] 抓取失败：%s", name, exc)
        return []


def fetch_all() -> tuple[list[dict[str, Any]], int]:
    """抓取所有启用的 RSS 源。返回 (条目列表, 成功抓到内容的源数量)。"""
    cfg = load_config()
    all_items: list[dict[str, Any]] = []
    active_sources = 0
    for src in cfg.get("sources", []):
        if not src.get("enabled"):
            continue
        if src.get("type") != "rss":
            # TODO: web 源的网页抓取后续实现
            logger.info("跳过非 RSS 源 [%s]（待网页抓取）", src.get("name"))
            continue
        items = fetch_source(src)
        if items:
            active_sources += 1
        all_items.extend(items)
    logger.info("共抓取 %d 条，来自 %d 个源", len(all_items), active_sources)
    return all_items, active_sources
