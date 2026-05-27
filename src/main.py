"""管道编排入口。

用法：
  python -m src.main                 生成今天的日报
  python -m src.main --dry-run       只抓取+标准化+粗筛，打印结果，不调 LLM 不写文件
  python -m src.main --date 2026-05-27   指定日期标注（抓取仍是实时）
详见技能 references/architecture.md。
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime

from .fetch import fetch_all
from .normalize import normalize, BEIJING
from .prefilter import prefilter
from .rank import rank_and_aggregate
from .render import build_context, render_html, write_reports

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("miao")


def run(dry_run: bool = False, date_str: str | None = None) -> int:
    now = datetime.now(BEIJING)
    if date_str:
        try:
            d = datetime.strptime(date_str, "%Y-%m-%d")
            now = now.replace(year=d.year, month=d.month, day=d.day)
        except ValueError:
            logger.error("--date 格式应为 YYYY-MM-DD")
            return 2

    # 1. 抓取
    raw_items, source_count = fetch_all()
    # 2. 标准化 + 去重
    items = normalize(raw_items)
    raw_count = len(items)
    # 3. 粗筛（24h + 关键词）
    candidates = prefilter(items, now=now)
    logger.info("粗筛后候选 %d 条（去重后 %d 条）", len(candidates), raw_count)

    if dry_run:
        print(f"\n=== DRY RUN：{source_count} 个源，去重后 {raw_count} 条，粗筛后 {len(candidates)} 条 ===\n")
        for it in candidates[:30]:
            print(f"[{it.get('category')}] {it.get('source')} | {it.get('published_at')}")
            print(f"    {it.get('title')}")
            print(f"    {it.get('url')}\n")
        return 0

    # 4. LLM 评分+摘要+标签+PM启发
    from .llm import analyze  # 延迟导入，dry-run 不需要

    enriched, pm_insights = analyze(candidates)
    logger.info("LLM 保留 %d 条", len(enriched))

    # 5. 排序聚合
    agg = rank_and_aggregate(enriched, raw_count=raw_count, source_count=source_count)

    # 6. 渲染 + 写出
    ctx = build_context(agg, pm_insights, now)
    html = render_html(ctx)
    path = write_reports(html, now)
    logger.info("已生成日报：%s", path)

    # 7. 可选邮件推送
    # TODO: 若配置了 SMTP_*，把 html 作为正文/附件发送给 MAIL_TO（见 architecture.md）
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="喵仔仔 AI 日报生成器")
    p.add_argument("--dry-run", action="store_true", help="只抓取+粗筛+打印，不调 LLM 不写文件")
    p.add_argument("--date", dest="date", default=None, help="指定日期 YYYY-MM-DD")
    args = p.parse_args()
    return run(dry_run=args.dry_run, date_str=args.date)


if __name__ == "__main__":
    sys.exit(main())
