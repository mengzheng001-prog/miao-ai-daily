"""LLM 层：调用 Claude Code 无头模式 `claude -p`，对粗筛后的资讯做
评分 + 中文摘要 + 打标签 + 生成 PM 启发，输出结构化 JSON。

鉴权：本地已登录 Claude Code 直接可用；CI 里靠环境变量 CLAUDE_CODE_OAUTH_TOKEN
（或 ANTHROPIC_API_KEY）。详见 references/architecture.md 与 scoring-and-tags.md。
"""
from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "sources.yaml"

# Prompt 模板与 references/scoring-and-tags.md 第四节保持一致。改这里要同步那边。
PROMPT_TEMPLATE = """你是 AI 行业资讯分析助手。下面是近 24 小时抓取并粗筛过的 AI 资讯列表（JSON）。
请逐条分析，并只输出一个 JSON 对象，不要任何额外解释或 markdown 代码块标记。
必须是合法 JSON：字符串内的双引号用 \" 转义，字符串内不要出现裸换行。

评分维度（每项 0-100）：source_authority_score, freshness_score, ai_relevance_score,
product_relevance_score, technical_impact_score, community_heat_score。
final_score = 加权和，权重依次 {weights}，取整。

过滤：营销软文、无实质转载、标题党、纯融资(除非影响行业格局)、与AI弱相关的，
给 final_score < 30 并在 keep=false 标记。

标签 tags：只能从这些里选 1-3 个，禁止自创：{tags}

摘要 summary_zh：50-100字中文，讲清发生了什么、关键点。
为什么值得关注 why_zh：不超过40字，从行业/产品视角说价值。

pm_insights：3-4 条『今日 AI 产品经理启发』，每条独立成项，不要糊成一段。
每项是对象：point=一句话重点（6-16字，会被加粗高亮），detail=25-50字展开说明。
只谈通用行业趋势和普适借鉴，不要提及或针对任何具体个人项目/产品名
（例如不得出现 ArchiAI、文旅调度平台等）。

输出格式：
{{"items":[{{"id":"<对应输入的id>","keep":true,"scores":{{"source_authority_score":0,"freshness_score":0,"ai_relevance_score":0,"product_relevance_score":0,"technical_impact_score":0,"community_heat_score":0}},"final_score":0,"summary_zh":"...","why_zh":"...","tags":["..."]}}],"pm_insights":[{{"point":"重点","detail":"说明"}}]}}

输入列表：
{payload}
"""


def _load_cfg() -> dict[str, Any]:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _build_prompt(items: list[dict[str, Any]]) -> str:
    cfg = _load_cfg()
    weights = cfg.get("scoring_weights", {})
    tags = cfg.get("allowed_tags", [])
    payload = json.dumps(
        [
            {
                "id": it["id"],
                "title": it.get("title", ""),
                "source": it.get("source", ""),
                "category": it.get("category", ""),
                "published_at": it.get("published_at", ""),
                "url": it.get("url", ""),
                "raw_text": (it.get("raw_text", "") or "")[:1000],
            }
            for it in items
        ],
        ensure_ascii=False,
    )
    return PROMPT_TEMPLATE.format(
        weights="/".join(str(v) for v in weights.values()),
        tags=tags,
        payload=payload,
    )


def _call_claude(prompt: str) -> str:
    """调用 claude -p，返回 stdout 文本。

    依赖 PATH 中的 claude CLI。CI 里 npm install -g @anthropic-ai/claude-code 后可用，
    鉴权走 CLAUDE_CODE_OAUTH_TOKEN / ANTHROPIC_API_KEY 环境变量（由 shell 环境注入）。
    """
    result = subprocess.run(
        ["claude", "-p", prompt],
        capture_output=True,
        text=True,
        timeout=600,
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude -p 失败: {result.stderr[:500]}")
    return result.stdout


def _extract_json(text: str) -> dict[str, Any]:
    """从可能夹杂多余文字的输出里截取第一个 { 到最后一个 } 并解析。"""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("LLM 输出中未找到 JSON")
    return json.loads(text[start : end + 1])


def _call_and_parse(prompt: str, attempts: int = 3) -> dict[str, Any]:
    """调用 claude -p 并解析 JSON，失败重试。

    claude -p 偶尔返回非法 JSON（中文里夹未转义引号、被截断等）。
    对无人值守的每日任务，单次失败不应让整份日报挂掉，故重试若干次。
    """
    last_err: Exception | None = None
    for i in range(attempts):
        try:
            return _extract_json(_call_claude(prompt))
        except (json.JSONDecodeError, ValueError, RuntimeError) as exc:
            last_err = exc
            logger.warning("第 %d/%d 次 LLM 解析失败：%s", i + 1, attempts, exc)
    raise RuntimeError(f"LLM 连续 {attempts} 次失败：{last_err}")


def analyze(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """对粗筛后的资讯做 LLM 分析。

    返回 (富化后的条目列表, pm_insights)。pm_insights 是 [{point, detail}, ...]。
    按 id 对齐回原始条目，缺失/非法标签做兜底。
    """
    if not items:
        return [], []
    cfg = _load_cfg()
    allowed = set(cfg.get("allowed_tags", []))

    prompt = _build_prompt(items)
    data = _call_and_parse(prompt)

    by_id = {r["id"]: r for r in data.get("items", []) if "id" in r}
    enriched: list[dict[str, Any]] = []
    for it in items:
        r = by_id.get(it["id"])
        if not r or not r.get("keep", False):
            continue  # 未保留或 LLM 漏判 → 兜底丢弃
        tags = [t for t in r.get("tags", []) if t in allowed][:3]
        it.update(
            {
                "keep": True,
                "scores": r.get("scores", {}),
                "final_score": int(r.get("final_score", 0)),
                "summary_zh": r.get("summary_zh", ""),
                "why_zh": r.get("why_zh", ""),
                "tags": tags,
            }
        )
        enriched.append(it)

    # 校验 pm_insights：只保留含 point/detail 的对象，做兜底
    raw_insights = data.get("pm_insights", [])
    pm_insights = [
        {"point": str(p.get("point", "")).strip(), "detail": str(p.get("detail", "")).strip()}
        for p in raw_insights
        if isinstance(p, dict) and p.get("point")
    ]
    return enriched, pm_insights
