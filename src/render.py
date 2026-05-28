"""渲染层：用 Jinja2 把聚合数据渲染成单文件 HTML。"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = ROOT / "templates"
REPORTS_DIR = ROOT / "reports"

WEEKDAYS = ["一", "二", "三", "四", "五", "六", "日"]


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
    ctx = dict(agg)
    ctx["date_cn"] = now.strftime("%Y年%m月%d日") + f"（周{WEEKDAYS[now.weekday()]}）"
    ctx["generated_at"] = "北京时间 " + now.strftime("%Y-%m-%d %H:%M")
    ctx["pm_insights"] = pm_insights
    ctx["fmt_publish"] = _fmt_publish  # 模板里调用
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
