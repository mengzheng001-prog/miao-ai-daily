"""每周总结：聚合最近 7 天的每日结构化数据（reports/data/*.json），
挑出全周重点、聚合关键词，再调 LLM 生成『本周 AI 重点回顾』，渲染成独立周报网页。

数据源是 render.write_daily_data 每天落盘的 JSON。没有任何数据则跳过，不报错。
有几天算几天（首次启用 / 数据不足时也能出一份）。
"""
from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .llm import _call_and_parse
from .render import (
    DATA_DIR,
    REPORTS_DIR,
    WEEKDAYS,
    _env,
    _fmt_publish,
    _join,
    _label,
    _pages_url,
)

logger = logging.getLogger(__name__)

WEEKLY_TOP_N = 12  # 周报展示的全周重点条数

WEEKLY_PROMPT = """下面是过去一周入选的 AI 资讯（标题+摘要+评分）。请生成『本周 AI 重点回顾』。
只输出一个 JSON 对象，不要额外解释或 markdown 代码块标记。必须是合法 JSON。
overview：一段 60-100 字的本周总览，点出本周 AI 行业最重要的趋势主线。
highlights：3-5 条本周重点，每条 point=一句话标题（8-18字，会被加粗高亮），detail=30-60字展开说明。
只谈通用行业趋势和普适借鉴，不要提及或针对任何具体个人项目/产品名（例如不得出现 ArchiAI、文旅调度平台等）。

输出格式：
{{"overview":"...","highlights":[{{"point":"重点","detail":"说明"}}]}}

本周资讯：
{payload}
"""


def load_recent_days(now: datetime, days: int = 7) -> list[dict[str, Any]]:
    """读最近 days 天（含今天）的每日 JSON，按日期升序返回。"""
    if not DATA_DIR.exists():
        return []
    start = (now - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    today = now.strftime("%Y-%m-%d")
    out: list[dict[str, Any]] = []
    for p in sorted(DATA_DIR.glob("*.json")):
        d = p.stem
        if start <= d <= today:
            try:
                out.append(json.loads(p.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("读取 %s 失败，跳过：%s", p.name, exc)
    return out


def aggregate_week(dailies: list[dict[str, Any]]) -> dict[str, Any]:
    """合并全周条目（按 url 去重保留最高分），挑 Top N，聚合关键词与统计。"""
    by_key: dict[str, dict[str, Any]] = {}
    for day in dailies:
        for it in (day.get("top3", []) + day.get("items", [])):
            key = it.get("url") or it.get("title")
            if not key:
                continue
            prev = by_key.get(key)
            if prev is None or it.get("final_score", 0) > prev.get("final_score", 0):
                item = dict(it)
                item["seen_date"] = day.get("date", "")
                by_key[key] = item

    merged = sorted(by_key.values(), key=lambda x: x.get("final_score", 0), reverse=True)

    kw: Counter[str] = Counter()
    for it in by_key.values():
        kw.update(it.get("tags", []))
    keywords = [{"tag": t, "count": c} for t, c in kw.most_common(20)]

    return {
        "top": merged[:WEEKLY_TOP_N],
        "keywords": keywords,
        "stats": {
            "days": len(dailies),
            "items": len(by_key),
            "shown": min(WEEKLY_TOP_N, len(merged)),
            "keywords": len(keywords),
        },
    }


def weekly_summary(top: list[dict[str, Any]]) -> dict[str, Any]:
    """调 LLM 生成本周总览 + 重点。失败则返回空，周报仍可出（只是少了综述）。"""
    if not top:
        return {"overview": "", "highlights": []}
    payload = json.dumps(
        [
            {
                "title": it.get("title", ""),
                "summary_zh": it.get("summary_zh", ""),
                "final_score": it.get("final_score", 0),
            }
            for it in top
        ],
        ensure_ascii=False,
    )
    try:
        data = _call_and_parse(WEEKLY_PROMPT.format(payload=payload))
        highlights = [
            {"point": str(h.get("point", "")).strip(), "detail": str(h.get("detail", "")).strip()}
            for h in data.get("highlights", [])
            if isinstance(h, dict) and h.get("point")
        ]
        return {"overview": str(data.get("overview", "")).strip(), "highlights": highlights}
    except Exception as exc:  # 综述失败不拖垮周报
        logger.warning("周报综述生成失败，留空：%s", exc)
        return {"overview": "", "highlights": []}


def build_weekly_context(
    agg: dict[str, Any], summary: dict[str, Any], now: datetime, dailies: list[dict[str, Any]]
) -> dict[str, Any]:
    """组装周报模板上下文。"""
    pages_url = _pages_url()
    start_dt = now - timedelta(days=6)
    # 本周覆盖到的每日入口（按日期倒序），方便从周报跳回当天日报
    day_index = [
        {
            "date": d.get("date", ""),
            "label": _label(d["date"]) if d.get("date") else "",
            "url": _join(pages_url, f"reports/{d['date']}.html"),
        }
        for d in sorted(dailies, key=lambda x: x.get("date", ""), reverse=True)
        if d.get("date")
    ]
    return {
        "range_cn": f"{start_dt.strftime('%Y年%m月%d日')} – {now.strftime('%m月%d日')}",
        "generated_at": "北京时间 " + now.strftime("%Y-%m-%d %H:%M"),
        "overview": summary.get("overview", ""),
        "highlights": summary.get("highlights", []),
        "top": agg["top"],
        "keywords": agg["keywords"],
        "stats": agg["stats"],
        "day_index": day_index,
        "pages_url": pages_url,
        "weekly_url": _join(pages_url, f"reports/weekly-{now.strftime('%Y-%m-%d')}.html"),
        "fmt_publish": _fmt_publish,
    }


def render_weekly(ctx: dict[str, Any]) -> str:
    return _env().get_template("weekly.html.jinja").render(**ctx)


def render_weekly_email(ctx: dict[str, Any]) -> str:
    return _env().get_template("weekly_email.html.jinja").render(**ctx)


def write_weekly(html: str, now: datetime) -> Path:
    """写周报归档 reports/weekly-YYYY-MM-DD.html，返回路径。"""
    REPORTS_DIR.mkdir(exist_ok=True)
    path = REPORTS_DIR / f"weekly-{now.strftime('%Y-%m-%d')}.html"
    path.write_text(html, encoding="utf-8")
    return path


def build_weekly(now: datetime) -> tuple[Path, dict[str, Any]] | None:
    """编排周报生成：读数据 → 聚合 → LLM 综述 → 渲染 → 落盘。

    返回 (周报文件路径, 渲染上下文)；无数据时返回 None。邮件发送由调用方负责。
    """
    dailies = load_recent_days(now, days=7)
    if not dailies:
        logger.warning("最近 7 天无每日数据（reports/data/*.json），跳过周报。")
        return None
    agg = aggregate_week(dailies)
    summary = weekly_summary(agg["top"])
    ctx = build_weekly_context(agg, summary, now, dailies)
    html = render_weekly(ctx)
    path = write_weekly(html, now)
    logger.info("已生成周报：%s（覆盖 %d 天，%d 条重点）", path, agg["stats"]["days"], agg["stats"]["shown"])
    return path, ctx
