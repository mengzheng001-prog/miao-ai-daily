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
from .render import DATA_DIR, build_context, render_html, write_daily_data, write_reports

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("miao")


def build_weekly_report(now: datetime) -> int:
    """生成每周总结并按需发邮件。无数据则跳过。供周日自动触发和 --weekly 手动触发共用。"""
    from .weekly import build_weekly, render_weekly_email

    result = build_weekly(now)
    if result is None:
        return 0
    path, ctx = result
    logger.info("已生成周报：%s", path)
    from .mailer import send_report
    send_report(render_weekly_email(ctx), subject=f"喵仔仔 AI 周报 - {ctx['range_cn']}")
    return 0


def run(dry_run: bool = False, date_str: str | None = None, force: bool = False) -> int:
    now = datetime.now(BEIJING)
    if date_str:
        try:
            d = datetime.strptime(date_str, "%Y-%m-%d")
            now = now.replace(year=d.year, month=d.month, day=d.day)
        except ValueError:
            logger.error("--date 格式应为 YYYY-MM-DD")
            return 2

    # 幂等：今天已成功生成过日报就跳过，避免外部触发器 + cron 兜底重复发两封邮件。
    # 判据是当天结构化数据已落盘（成功跑完才会写）。--force 可强制重跑。
    if not dry_run and not force:
        if (DATA_DIR / f"{now.strftime('%Y-%m-%d')}.json").exists():
            logger.info("今天 %s 已生成过日报，跳过（避免重复）。如需重跑用 --force。", now.strftime("%Y-%m-%d"))
            return 0

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

    # 健壮性：若 LLM 全部失败/0 条入选，跳过渲染/提交/邮件，保留之前的好报告。
    # 否则一次坏运行（如 Claude session 限额、网络抖动）会覆盖前一次的好报告，
    # 用户看到的就是空壳。
    if not enriched:
        logger.warning("LLM 0 条入选，跳过本次生成；保留已有报告不动。")
        return 0

    # 5. 排序聚合
    agg = rank_and_aggregate(enriched, raw_count=raw_count, source_count=source_count)

    # 6. 渲染 + 写出（HTML 归档 + index，再把结构化数据落盘供周报聚合）
    ctx = build_context(agg, pm_insights, now)
    html = render_html(ctx)
    path = write_reports(html, now)
    write_daily_data(agg, pm_insights, now)
    logger.info("已生成日报：%s", path)

    # 7. 邮件推送（配置了 SMTP_* 才发，否则自动跳过）
    from .render import render_email
    from .mailer import send_report

    send_report(render_email(ctx), subject=f"喵仔仔 AI 日报 - {ctx['date_cn']}")

    # 8. 每周日（weekday()==6）日报跑完后自动追加生成周报
    if now.weekday() == 6:
        logger.info("今天是周日，生成本周总结……")
        build_weekly_report(now)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="喵仔仔 AI 日报生成器")
    p.add_argument("--dry-run", action="store_true", help="只抓取+粗筛+打印，不调 LLM 不写文件")
    p.add_argument("--date", dest="date", default=None, help="指定日期 YYYY-MM-DD")
    p.add_argument("--weekly", action="store_true", help="只生成本周总结（聚合最近7天已存数据），不跑当天日报")
    p.add_argument("--force", action="store_true", help="强制重跑，忽略今天已生成的幂等跳过")
    args = p.parse_args()

    if args.weekly:
        now = datetime.now(BEIJING)
        if args.date:
            try:
                d = datetime.strptime(args.date, "%Y-%m-%d")
                now = now.replace(year=d.year, month=d.month, day=d.day)
            except ValueError:
                logger.error("--date 格式应为 YYYY-MM-DD")
                return 2
        return build_weekly_report(now)

    return run(dry_run=args.dry_run, date_str=args.date, force=args.force)


if __name__ == "__main__":
    sys.exit(main())
