"""排序与聚合层：按 final_score 排序取 Top10/Top3，聚合关键词，统计来源生态。"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any


def rank_and_aggregate(
    enriched: list[dict[str, Any]],
    raw_count: int,
    source_count: int,
) -> dict[str, Any]:
    """从富化后的条目生成渲染所需的全部聚合数据。"""
    # 排序：final_score 降序，并列时来源权威度高者优先
    ordered = sorted(
        enriched,
        key=lambda x: (x.get("final_score", 0), x.get("scores", {}).get("source_authority_score", 0)),
        reverse=True,
    )
    top10 = ordered[:10]      # 全部入选，用于关键词/来源生态/原文列表/统计
    top3 = ordered[:3]        # 今日最值得关注
    featured = ordered[3:10]  # 精选资讯：第4名起，不与 Top3 重复

    # 关键词聚合（只统计入选 Top10 的标签）
    tag_counter: Counter[str] = Counter()
    for it in top10:
        tag_counter.update(it.get("tags", []))
    keywords = [{"tag": t, "count": c} for t, c in tag_counter.most_common()]

    # 来源生态：按 类别+来源 统计 Top10 贡献条数
    eco_counter: dict[tuple[str, str], int] = defaultdict(int)
    for it in top10:
        eco_counter[(it.get("category", ""), it.get("source", ""))] += 1
    source_eco = [
        {"category": cat, "name": name, "count": cnt}
        for (cat, name), cnt in sorted(eco_counter.items(), key=lambda kv: (-kv[1], kv[0]))
    ]

    # 原文来源列表（第10段）
    source_list = [
        {"title": it.get("title", ""), "source": it.get("source", ""), "url": it.get("url", "")}
        for it in top10
    ]

    return {
        "top3": top3,
        "items": featured,
        "keywords": keywords,
        "source_eco": source_eco,
        "source_list": source_list,
        "stats": {
            "sources": source_count,
            "raw": raw_count,
            "selected": len(top10),
            "keywords": len(keywords),
        },
    }
