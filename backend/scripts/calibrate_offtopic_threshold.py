"""一次性校准脚本：跑 offtopic_corpus.yaml 所有样本，输出 dense top1 分布，建议阈值。

跑法（容器内）：
    docker compose exec backend python scripts/calibrate_offtopic_threshold.py

前置依赖：
    - llm_configs 表预填 is_default=true 的记录（normalize_intent 要用）
    - embedding_service 健康（dense 嵌入）
    - Qdrant 已 import 模板（lib_manager.py import）

输出阶段：
    1. 每条样本：input → normalized → top1_dense_score
    2. off_topic 段统计：max / p95 / mean
    3. marginal_ic 段统计：min / p5 / mean
    4. 建议阈值（取两段之间，偏向 marginal_ic_min 侧）
"""
from __future__ import annotations
import asyncio
import statistics
import sys
from pathlib import Path

import yaml

# 让脚本能直接 import app 包
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from qdrant_client.models import Filter, FieldCondition, MatchValue  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.database import AsyncSessionLocal  # noqa: E402
from app.core.vector_store import get_qdrant  # noqa: E402
from app.services.embedding_client import get_embedding_client  # noqa: E402
from app.services.intent.normalizer import normalize_intent  # noqa: E402
from app.services.registry import get_registry  # noqa: E402


_CORPUS_PATH = Path(__file__).resolve().parent.parent / "tests" / "data" / "offtopic_corpus.yaml"


async def _dense_top1(text: str, code_type: str) -> float:
    """对单条文本拿 dense top1 余弦分数（绕开 RRF/reranker）。"""
    embed_client = get_embedding_client()
    qdrant = get_qdrant()
    settings = get_settings()
    embed_result = await embed_client.embed([text], modes=["dense"])
    dense_vec = embed_result["dense"][0]

    query_filter = Filter(
        must=[FieldCondition(key="code_type", match=MatchValue(value=code_type))]
    )
    res = await qdrant.query_points(
        collection_name=settings.qdrant_collection,
        query=dense_vec,
        using="dense",
        limit=1,
        query_filter=query_filter,
    )
    return float(res.points[0].score) if res.points else 0.0


async def _best_overall_dense(text: str, selected_code_type: str) -> float:
    """FEAT-15：模拟生产 gate 1 的判定信号 `best_overall = max(selected, max(other))`。

    生产侧 pipeline_preview 用 `_compute_cross_code_type_scores` 对每个 registered
    code_type 各跑一次 dense top1，取最大值。本函数复刻同样的语义供阈值校准。
    `selected_code_type` 仅决定结果里"选中那条"的列；最大值是跨全库取的。
    """
    registry = get_registry()
    scores: list[float] = []
    for ct in registry.all():
        scores.append(await _dense_top1(text, ct.id))
    return max(scores) if scores else 0.0


def _expand_off_topic(raw: list[dict]) -> list[tuple[str, str, str]]:
    """off_topic 段每条 sample 按 code_types 列表展开为多条 case。"""
    out = []
    for s in raw:
        for ct in s.get("code_types") or [s.get("code_type", "assertion")]:
            out.append((s["id"], ct, s["input"]))
    return out


def _expand_marginal(raw: list[dict]) -> list[tuple[str, str, str]]:
    return [(s["id"], s["code_type"], s["input"]) for s in raw]


async def main() -> None:
    corpus = yaml.safe_load(_CORPUS_PATH.read_text(encoding="utf-8"))
    off_cases = _expand_off_topic(corpus.get("off_topic", []))
    marg_cases = _expand_marginal(corpus.get("marginal_ic", []))

    async def _measure(cases: list[tuple[str, str, str]], label: str):
        print("=" * 110)
        print(f"{label} ({len(cases)} cases)")
        print("=" * 110)
        print(
            f"{'id':<35}{'code_type':<12}{'score_orig':>12}{'score_norm':>12}"
            f"{'score_overall':>15}  normalized"
        )
        print("-" * 110)
        scores_orig: list[float] = []
        scores_norm: list[float] = []
        scores_overall: list[float] = []
        async with AsyncSessionLocal() as db:
            for cid, ct, text in cases:
                try:
                    normalized, _ = await normalize_intent(text, db)
                except Exception as e:
                    print(f"{cid:<35}{ct:<12}  normalize failed: {e}")
                    continue
                s_orig = await _dense_top1(text, ct)
                s_norm = await _dense_top1(normalized, ct)
                # FEAT-15：production gate 1 实际用 best_overall（全库 max）做判定，
                # 阈值推荐必须基于这个分布，不能用 selected-only 的 score_orig 误导。
                s_overall = await _best_overall_dense(text, ct)
                scores_orig.append(s_orig)
                scores_norm.append(s_norm)
                scores_overall.append(s_overall)
                preview = (normalized[:48] + "…") if len(normalized) > 48 else normalized
                print(
                    f"{cid:<35}{ct:<12}{s_orig:>12.4f}{s_norm:>12.4f}"
                    f"{s_overall:>15.4f}  {preview}"
                )
        return scores_orig, scores_norm, scores_overall

    off_orig, off_norm, off_overall = await _measure(off_cases, "OFF_TOPIC 段")
    print()
    marg_orig, marg_norm, marg_overall = await _measure(marg_cases, "MARGINAL_IC 段")

    def _stats(label: str, scores: list[float]) -> dict:
        if not scores:
            return {}
        srt = sorted(scores)
        return {
            "n": len(srt),
            "min": min(srt),
            "p5": srt[max(0, int(len(srt) * 0.05))],
            "mean": statistics.mean(srt),
            "p95": srt[min(len(srt) - 1, int(len(srt) * 0.95))],
            "max": max(srt),
        }

    def _print_compare(label_a, off, label_b, marg):
        a = _stats("off", off)
        b = _stats("marg", marg)
        print(f"  {label_a}:")
        print(f"    off_topic    n={a['n']}  min={a['min']:.4f}  mean={a['mean']:.4f}  max={a['max']:.4f}")
        print(f"    marginal_ic  n={b['n']}  min={b['min']:.4f}  mean={b['mean']:.4f}  max={b['max']:.4f}")
        gap = b['min'] - a['max']
        if gap > 0:
            mid = round(a['max'] + gap / 2, 2)
            print(f"    分离: off_max ({a['max']:.4f}) < marg_min ({b['min']:.4f})  gap={gap:.4f}  → 建议阈值={mid}")
        else:
            print(f"    重叠: off_max ({a['max']:.4f}) >= marg_min ({b['min']:.4f})  overlap={-gap:.4f}")
            print(f"    若必须取阈值: {max(0.0, b['min'] - 0.02):.2f}（偏向 marg_min 侧）")

    print()
    print("=" * 100)
    print("STATISTICS")
    print("=" * 100)
    print()
    _print_compare("embed=ORIGINAL_INTENT, score=SELECTED_ONLY (诊断)", off_orig, "...", marg_orig)
    print()
    _print_compare("embed=NORMALIZED, score=SELECTED_ONLY (诊断)", off_norm, "...", marg_norm)
    print()
    # FEAT-15：production gate 1 用 best_overall（embed=ORIGINAL，score=全库 max）。
    # 推荐阈值必须基于这一行的分布，前两行只是排查诊断。
    _print_compare(
        "embed=ORIGINAL_INTENT, score=BEST_OVERALL (生产 gate 1 实际语义)",
        off_overall, "...", marg_overall,
    )

    # 建议的 env 行：让运维直接粘贴进 .env 即可生效（无需改代码 / 重 build 镜像）。
    # 用 best_overall 分布做推荐——和生产 gate 1 的判定信号严格对齐。
    if off_overall and marg_overall:
        off_max = max(off_overall)
        marg_min = min(marg_overall)
        gap = marg_min - off_max
        if gap > 0:
            recommended = round(off_max + gap / 2, 2)
        else:
            recommended = round(max(0.0, marg_min - 0.02), 2)
        print()
        print("=" * 100)
        print("写入 .env（生效需重启 backend）—— 基于 best_overall 分布：")
        print(f"  OFFTOPIC_DENSE_THRESHOLD={recommended}")
        print("=" * 100)


if __name__ == "__main__":
    asyncio.run(main())
