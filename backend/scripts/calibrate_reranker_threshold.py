"""一次性校准脚本：对 template_selection_corpus + template_confusion_corpus 跑真 RAG
（stage1 + stage2 + stage3 reranker），输出每条 intent 的"correct_template 的 reranker
score"以及"confusion_template 的 reranker score"，给 A9 reranker_min_score_threshold
建议合适阈值。

跑法（容器内）：
    docker compose exec backend python scripts/calibrate_reranker_threshold.py

前置依赖：
    - embedding_service 健康（dense / sparse / colbert）
    - Qdrant 已 import 全部 10 个模板
    - llm_configs 表预填 is_default=true 的记录——normalize_intent(text, db) 第三参
      `llm` 是 Optional，省略时函数内部自动 fetch default（见 services/intent/normalizer.py:17）。
      所以脚本可以省略 llm 参数；但 default 记录必须存在，否则 get_default_llm_client 抛错。

输出阶段：
    1. selection_corpus 每条：input → normalized → top-N candidates with reranker score
       → correct 模板的 score（若 correct 不在 top-N 列出 "MISS"）
    2. confusion_corpus 每条：correct 模板 score + confusion 模板 score（若在 top-N）
    3. 汇总：correct 段 p10/p50/p90、confusion 段 p10/p50/p90、建议阈值

阈值取法：让大多数 correct 通过、大多数 confusion 拦下 ——
    建议阈值 = max(correct_p10 - epsilon, confusion_p50 + epsilon)
若两段重叠严重（correct_p10 < confusion_p50）→ 标定无解，需先在 differentiators /
description 上下功夫，重训 reranker 或换 model。

注意：本脚本不应进 CI（依赖 live embedding/qdrant）。结果是给人工拍板用的。
"""
from __future__ import annotations
import asyncio
import statistics
import sys
from pathlib import Path

import yaml

# 让脚本能直接 import app 包
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import AsyncSessionLocal  # noqa: E402
from app.services.intent.normalizer import normalize_intent  # noqa: E402
from app.services.rag.engine import rag_retrieve  # noqa: E402


_TESTS_DATA = Path(__file__).resolve().parent.parent / "tests" / "data"
_SELECTION_CORPUS = _TESTS_DATA / "template_selection_corpus.yaml"
_CONFUSION_CORPUS = _TESTS_DATA / "template_confusion_corpus.yaml"


def _stats(label: str, scores: list[float]) -> None:
    if not scores:
        print(f"  {label}: (no data)")
        return
    srt = sorted(scores)
    n = len(srt)
    p10 = srt[max(0, int(n * 0.10))]
    p50 = srt[max(0, int(n * 0.50))]
    p90 = srt[min(n - 1, int(n * 0.90))]
    print(
        f"  {label}: n={n} min={min(srt):.4f} p10={p10:.4f} p50={p50:.4f} "
        f"p90={p90:.4f} max={max(srt):.4f} mean={statistics.mean(srt):.4f}"
    )


async def _measure_selection_corpus() -> list[float]:
    """selection corpus 每条：correct 应该高分。返回 correct_template 的 score 列表。"""
    print("=" * 100)
    print("SELECTION CORPUS（correct_template 的 reranker score）")
    print("=" * 100)
    raw = yaml.safe_load(_SELECTION_CORPUS.read_text(encoding="utf-8")) or {}
    cases = raw.get("correct_mapping", []) or []
    correct_scores: list[float] = []
    async with AsyncSessionLocal() as db:
        for c in cases:
            intent = c["intent"]
            code_type = c["code_type"]
            expected = c["expected_template"]
            try:
                normalized, _ = await normalize_intent(intent, db)
                candidates = await rag_retrieve(normalized, db, code_type=code_type)
            except Exception as e:
                print(f"  [{c['id']}] retrieve failed: {e}")
                continue
            sel = next((x for x in candidates if x["template_id"] == expected), None)
            if sel is None:
                print(
                    f"  [{c['id']}] MISS — expected {expected} 未进 stage3 top-{len(candidates)}"
                )
                continue
            score = float(sel["score"])
            correct_scores.append(score)
            top = ", ".join(f"{x['template_id']}={x['score']:.3f}" for x in candidates[:3])
            print(f"  [{c['id']}] correct_score={score:.4f}  top3=[{top}]")
    return correct_scores


async def _measure_confusion_corpus() -> tuple[list[float], list[float]]:
    """confusion corpus 每条：correct vs confusion 的 reranker score。

    返回 (correct_scores, confusion_scores)。若任一 template_id 没进 top-N 则跳过。
    """
    print()
    print("=" * 100)
    print("CONFUSION CORPUS（correct vs confusion 的 reranker score）")
    print("=" * 100)
    raw = yaml.safe_load(_CONFUSION_CORPUS.read_text(encoding="utf-8")) or {}
    cases = raw.get("confusion_pairs", []) or []
    correct_scores: list[float] = []
    confusion_scores: list[float] = []
    async with AsyncSessionLocal() as db:
        for c in cases:
            intent = c["input"]
            code_type = c["code_type"]
            correct = c["correct_template"]
            confusion = c["confusion_template"]
            try:
                normalized, _ = await normalize_intent(intent, db)
                candidates = await rag_retrieve(normalized, db, code_type=code_type)
            except Exception as e:
                print(f"  [{c['id']}] retrieve failed: {e}")
                continue
            sel = {x["template_id"]: float(x["score"]) for x in candidates}
            c_score = sel.get(correct)
            x_score = sel.get(confusion)
            if c_score is not None:
                correct_scores.append(c_score)
            if x_score is not None:
                confusion_scores.append(x_score)
            print(
                f"  [{c['id']}] correct({correct})={c_score!s:>10}  "
                f"confusion({confusion})={x_score!s:>10}"
            )
    return correct_scores, confusion_scores


async def main() -> None:
    selection_correct = await _measure_selection_corpus()
    confusion_correct, confusion_wrong = await _measure_confusion_corpus()

    print()
    print("=" * 100)
    print("STATISTICS")
    print("=" * 100)
    all_correct = selection_correct + confusion_correct
    _stats("ALL correct       ", all_correct)
    _stats("selection correct ", selection_correct)
    _stats("confusion correct ", confusion_correct)
    _stats("confusion wrong   ", confusion_wrong)

    print()
    print("=" * 100)
    print("THRESHOLD SUGGESTION（A9 reranker_min_score_threshold）")
    print("=" * 100)
    if not all_correct:
        print("  无 correct 数据 → 无法标定")
        return
    correct_srt = sorted(all_correct)
    correct_p10 = correct_srt[max(0, int(len(correct_srt) * 0.10))]
    if confusion_wrong:
        wrong_srt = sorted(confusion_wrong)
        wrong_p50 = wrong_srt[max(0, int(len(wrong_srt) * 0.50))]
        gap = correct_p10 - wrong_p50
        print(f"  correct_p10 = {correct_p10:.4f}")
        print(f"  wrong_p50   = {wrong_p50:.4f}")
        print(f"  gap         = {gap:.4f}")
        if gap > 0:
            mid = round((correct_p10 + wrong_p50) / 2, 2)
            print(
                f"  → 建议阈值 = {mid}（位于 correct_p10 与 wrong_p50 中点；"
                "可放过≥90% correct、拦截≥50% wrong）"
            )
        else:
            print(
                "  → 两段重叠：reranker 在 confusion 对上区分度不足。建议先优化 differentiators / "
                "description；阈值若取 wrong_p50 会同时误拦≥10% correct。"
            )
    else:
        # 没有 confusion_wrong 数据（confusion template 未进 stage3 top-N）
        suggested = round(max(correct_p10 - 0.05, 0.10), 2)
        print(f"  correct_p10 = {correct_p10:.4f}")
        print(f"  无 confusion 干扰数据 → 保守取阈值 = {suggested}（correct_p10 - 0.05）")

    print()
    print("写入 .env（生效需重启 backend）：")
    print("  STEP1_RERANKER_GATE_ENABLED=true")
    print("  RERANKER_MIN_SCORE_THRESHOLD=<上面建议值>")


if __name__ == "__main__":
    asyncio.run(main())
