"""LLM 层：调用 Claude Code 无头模式 `claude -p`，对粗筛后的资讯做
评分 + 中文摘要 + 打标签 + 生成 PM 启发，输出结构化 JSON。

为避免一次性生成大量摘要导致单次调用超时，资讯按小批处理（每批 BATCH_SIZE 条），
PM 启发在所有批次完成后单独一调用生成。单批/单次失败会跳过，不拖垮整份日报。

鉴权：本地已登录 Claude Code 直接可用；CI 里靠环境变量 CLAUDE_CODE_OAUTH_TOKEN
（或 ANTHROPIC_API_KEY）。详见 references/architecture.md 与 scoring-and-tags.md。
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "sources.yaml"

# 跑评分/摘要用的模型：Sonnet 足够且比 Opus 快（可用 MIAO_LLM_MODEL 覆盖）
MODEL = os.environ.get("MIAO_LLM_MODEL", "sonnet")
# 送进 LLM 的最大条数（可用 MIAO_MAX_ITEMS 覆盖）
MAX_LLM_ITEMS = int(os.environ.get("MIAO_MAX_ITEMS", "22"))
# 每批条数：批小则单次调用快、稳，不易超时（可用 MIAO_BATCH_SIZE 覆盖）
BATCH_SIZE = int(os.environ.get("MIAO_BATCH_SIZE", "6"))

# 批分析 Prompt（只评分/摘要/标签，不含 pm_insights）。
# 与 references/scoring-and-tags.md 保持一致，改这里要同步那边。
ITEM_PROMPT = """你是 AI 行业资讯分析助手。下面是一批近 24 小时的 AI 资讯（JSON）。
逐条分析，只输出一个 JSON 对象，不要任何额外解释或 markdown 代码块标记。
必须是合法 JSON：字符串内双引号用 \\" 转义，字符串内不要出现裸换行。

评分维度（每项 0-100）：source_authority_score, freshness_score, ai_relevance_score,
product_relevance_score, technical_impact_score, community_heat_score。
final_score = 加权和，权重依次 {weights}，取整。

过滤：营销软文、无实质转载、标题党、纯融资(除非影响行业格局)、与AI弱相关的，
给 final_score < 30 并 keep=false。

标签 tags：只能从这些里选 1-3 个，禁止自创：{tags}
摘要 summary_zh：50-100字中文，讲清发生了什么、关键点。
为什么值得关注 why_zh：不超过40字，从行业/产品视角说价值。

输出格式：
{{"items":[{{"id":"<输入的id>","keep":true,"scores":{{"source_authority_score":0,"freshness_score":0,"ai_relevance_score":0,"product_relevance_score":0,"technical_impact_score":0,"community_heat_score":0}},"final_score":0,"summary_zh":"...","why_zh":"...","tags":["..."]}}]}}

输入列表：
{payload}
"""

# PM 启发 Prompt（基于已入选条目的标题+摘要单独生成）。
INSIGHT_PROMPT = """下面是今天入选的 AI 资讯（标题+摘要）。请提炼 3-4 条『今日 AI 产品经理启发』。
只输出一个 JSON 对象，不要额外解释或 markdown。必须是合法 JSON。

每条独立成项、不要糊成一段。每项是对象：point=一句话重点（6-16字，会被加粗高亮），
detail=25-50字展开说明。只谈通用行业趋势和普适借鉴，不要提及或针对任何具体个人
项目/产品名（例如不得出现 ArchiAI、文旅调度平台等）。

输出格式：
{{"pm_insights":[{{"point":"重点","detail":"说明"}}]}}

入选资讯：
{payload}
"""


def _clean_text(text: str) -> str:
    """去掉 HTML 标签、压缩空白、截断。RSS 摘要常含大量噪音 HTML。"""
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", text).strip()[:500]


def _load_cfg() -> dict[str, Any]:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _chunks(seq: list[Any], n: int):
    for i in range(0, len(seq), n):
        yield seq[i : i + n]


def _build_item_prompt(items: list[dict[str, Any]]) -> str:
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
                "raw_text": _clean_text(it.get("raw_text", "")),
            }
            for it in items
        ],
        ensure_ascii=False,
    )
    return ITEM_PROMPT.format(
        weights="/".join(str(v) for v in weights.values()),
        tags=tags,
        payload=payload,
    )


def _build_insight_prompt(kept: list[dict[str, Any]]) -> str:
    payload = json.dumps(
        [{"title": it.get("title", ""), "summary_zh": it.get("summary_zh", "")} for it in kept],
        ensure_ascii=False,
    )
    return INSIGHT_PROMPT.format(payload=payload)


def _call_claude(prompt: str, timeout: int = 180) -> str:
    """调用 claude -p，返回 stdout 文本。

    依赖 PATH 中的 claude CLI。CI 里 npm install -g @anthropic-ai/claude-code 后可用，
    鉴权走 CLAUDE_CODE_OAUTH_TOKEN / ANTHROPIC_API_KEY 环境变量。
    指定 --model 用更快的模型；小批 + 短 timeout 避免卡死。
    """
    result = subprocess.run(
        ["claude", "-p", "--model", MODEL, "--output-format", "text", prompt],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"claude -p 退出码 {result.returncode}; "
            f"stderr={result.stderr[:400]!r}; stdout={result.stdout[:400]!r}"
        )
    return result.stdout


def _extract_json(text: str) -> dict[str, Any]:
    """从可能夹杂多余文字的输出里截取第一个 { 到最后一个 } 并解析。"""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("LLM 输出中未找到 JSON")
    return json.loads(text[start : end + 1])


def _call_and_parse(prompt: str, attempts: int = 2) -> dict[str, Any]:
    """调用 claude -p 并解析 JSON，失败（含超时/非法JSON）重试。"""
    last_err: Exception | None = None
    for i in range(attempts):
        try:
            return _extract_json(_call_claude(prompt))
        except (json.JSONDecodeError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
            last_err = exc
            logger.warning("第 %d/%d 次 LLM 调用失败：%s", i + 1, attempts, exc)
    raise RuntimeError(f"LLM 连续 {attempts} 次失败：{last_err}")


def _merge_batch(
    batch: list[dict[str, Any]], data: dict[str, Any], allowed: set[str]
) -> list[dict[str, Any]]:
    """把一批的 LLM 结果按 id 合并回原始条目，过滤非法标签，丢弃未保留项。"""
    by_id = {r["id"]: r for r in data.get("items", []) if "id" in r}
    out: list[dict[str, Any]] = []
    for it in batch:
        r = by_id.get(it["id"])
        if not r or not r.get("keep", False):
            continue
        it.update(
            {
                "keep": True,
                "scores": r.get("scores", {}),
                "final_score": int(r.get("final_score", 0)),
                "summary_zh": r.get("summary_zh", ""),
                "why_zh": r.get("why_zh", ""),
                "tags": [t for t in r.get("tags", []) if t in allowed][:3],
            }
        )
        out.append(it)
    return out


def analyze(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """分批做 LLM 分析。返回 (富化后的条目列表, pm_insights)。

    pm_insights 是 [{point, detail}, ...]。单批或启发调用失败会跳过，不抛异常拖垮全局。
    """
    if not items:
        return [], []
    cfg = _load_cfg()
    allowed = set(cfg.get("allowed_tags", []))

    # 控制总条数：优先保官方(C)/专家(B)源，社区(A)源补足
    if len(items) > MAX_LLM_ITEMS:
        non_a = [it for it in items if it.get("category") != "A"]
        a = [it for it in items if it.get("category") == "A"]
        items = (non_a + a)[:MAX_LLM_ITEMS]

    # 分批评分/摘要/标签
    enriched: list[dict[str, Any]] = []
    batches = list(_chunks(items, BATCH_SIZE))
    for idx, batch in enumerate(batches, 1):
        try:
            data = _call_and_parse(_build_item_prompt(batch))
            enriched.extend(_merge_batch(batch, data, allowed))
            logger.info("批 %d/%d 完成，累计保留 %d 条", idx, len(batches), len(enriched))
        except Exception as exc:  # 单批失败跳过，保住其余批次
            logger.warning("批 %d/%d 失败，跳过：%s", idx, len(batches), exc)

    if not enriched:
        return [], []

    # 基于已入选条目（取分数最高的若干条）单独生成 PM 启发
    top = sorted(enriched, key=lambda x: x.get("final_score", 0), reverse=True)[:10]
    pm_insights: list[dict[str, str]] = []
    try:
        data = _call_and_parse(_build_insight_prompt(top))
        pm_insights = [
            {"point": str(p.get("point", "")).strip(), "detail": str(p.get("detail", "")).strip()}
            for p in data.get("pm_insights", [])
            if isinstance(p, dict) and p.get("point")
        ]
    except Exception as exc:
        logger.warning("PM 启发生成失败，留空：%s", exc)

    return enriched, pm_insights
