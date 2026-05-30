"""渲染层：用 Jinja2 把聚合数据渲染成单文件 HTML。"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = ROOT / "templates"
REPORTS_DIR = ROOT / "reports"
DATA_DIR = REPORTS_DIR / "data"          # 每日结构化数据，周报据此聚合

WEEKDAYS = ["一", "二", "三", "四", "五", "六", "日"]

# 日报归档文件名：2026-05-28.html；周报归档：weekly-2026-05-31.html
DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.html$")
WEEKLY_RE = re.compile(r"^weekly-(\d{4}-\d{2}-\d{2})\.html$")

DEFAULT_PAGES_URL = "https://mengzheng001-prog.github.io/miao-ai-daily/"


def _pages_url() -> str:
    return os.environ.get("PAGES_URL", DEFAULT_PAGES_URL)


def _join(base: str, path: str) -> str:
    """拼公开网址，避免双斜杠或缺斜杠。"""
    return base.rstrip("/") + "/" + path.lstrip("/")


def _label(date_str: str) -> str:
    """'2026-05-28' → 'MM-DD（周X）'。"""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return dt.strftime("%m-%d") + f"（周{WEEKDAYS[dt.weekday()]}）"


def _recent_reports(now: datetime, pages_url: str, days: int = 7) -> list[dict[str, Any]]:
    """扫描归档目录，返回最近 days 天的日报入口（含今天，倒序）。"""
    dates: set[str] = set()
    if REPORTS_DIR.exists():
        for p in REPORTS_DIR.iterdir():
            m = DATE_RE.match(p.name)
            if m:
                dates.add(m.group(1))
    today = now.strftime("%Y-%m-%d")
    dates.add(today)  # 今天此刻可能还没落盘，手动补上
    return [
        {
            "date": d,
            "label": _label(d),
            "url": _join(pages_url, f"reports/{d}.html"),
            "is_today": d == today,
        }
        for d in sorted(dates, reverse=True)[:days]
    ]


def _latest_weekly(pages_url: str) -> dict[str, Any] | None:
    """返回最新一份周报入口，没有则 None（首页据此决定是否显示周报入口）。"""
    if not REPORTS_DIR.exists():
        return None
    weeks = [m.group(1) for p in REPORTS_DIR.iterdir() if (m := WEEKLY_RE.match(p.name))]
    if not weeks:
        return None
    d = sorted(weeks, reverse=True)[0]
    return {"date": d, "label": _label(d), "url": _join(pages_url, f"reports/weekly-{d}.html")}


def _fmt_publish(iso: str | None) -> str:
    """把 ISO 时间格式化为 'MM-DD HH:MM'（北京时间）。"""
    if not iso:
        return "时间未知"
    try:
        dt = datetime.fromisoformat(iso)
        return dt.strftime("%m-%d %H:%M")
    except ValueError:
        return iso


def build_context(agg: dict[str, Any], pm_insights: list[dict[str, str]], now: datetime) -> dict[str, Any]:
    """组装模板上下文，约定见 references/architecture.md。"""
    pages_url = _pages_url()
    today = now.strftime("%Y-%m-%d")
    ctx = dict(agg)
    ctx["date_cn"] = now.strftime("%Y年%m月%d日") + f"（周{WEEKDAYS[now.weekday()]}）"
    ctx["generated_at"] = "北京时间 " + now.strftime("%Y-%m-%d %H:%M")
    ctx["pm_insights"] = pm_insights
    ctx["fmt_publish"] = _fmt_publish  # 模板里调用
    # GitHub Pages 站点根地址。可通过环境变量覆盖。
    ctx["pages_url"] = pages_url
    # 当天这份报告的固定归档网址：邮件按钮指向它，昨天的邮件永远打开昨天的内容。
    ctx["report_url"] = _join(pages_url, f"reports/{today}.html")
    # 最近 7 天历史 + 最新周报入口（首页/归档页可回看）。
    ctx["history"] = _recent_reports(now, pages_url, days=7)
    ctx["weekly_link"] = _latest_weekly(pages_url)
    return ctx


def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
    )


def render_html(ctx: dict[str, Any]) -> str:
    """渲染浏览器版（report.html.jinja）。"""
    return _env().get_template("report.html.jinja").render(**ctx)


def render_email(ctx: dict[str, Any]) -> str:
    """渲染邮件版（email.html.jinja）：内联样式、纯色，适配邮件客户端。"""
    return _env().get_template("email.html.jinja").render(**ctx)


def write_reports(html: str, now: datetime) -> Path:
    """写当天归档 + 更新 index.html，返回当天文件路径。"""
    REPORTS_DIR.mkdir(exist_ok=True)
    dated = REPORTS_DIR / f"{now.strftime('%Y-%m-%d')}.html"
    dated.write_text(html, encoding="utf-8")
    (ROOT / "index.html").write_text(html, encoding="utf-8")
    return dated


def write_daily_data(agg: dict[str, Any], pm_insights: list[dict[str, str]], now: datetime) -> Path:
    """把当天结构化数据存成 JSON，供每周总结聚合。返回文件路径。

    存 top3+items（含分数/摘要/标签/原文链接）即覆盖完整 Top10，周报据此挑全周重点。
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    d = now.strftime("%Y-%m-%d")
    payload = {
        "date": d,
        "date_cn": now.strftime("%Y年%m月%d日") + f"（周{WEEKDAYS[now.weekday()]}）",
        "top3": agg.get("top3", []),
        "items": agg.get("items", []),
        "keywords": agg.get("keywords", []),
        "stats": agg.get("stats", {}),
        "pm_insights": pm_insights,
    }
    path = DATA_DIR / f"{d}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
