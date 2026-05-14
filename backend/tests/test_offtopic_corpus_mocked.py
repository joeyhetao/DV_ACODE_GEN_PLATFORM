"""Mock-LLM 回归测试：验证 pipeline_preview 对 offtopic_corpus.yaml 每条样本的路由。

mock `dense_top1_score` 模拟"已经过 embedding 的 top1 余弦分数"——重点测的是
"pipeline 看到分数 < 阈值早返"和"看到分数 >= 阈值正常走 RAG/LLM"的逻辑分支。
**不**测 bge-m3 嵌入本身的分类准确性——那个由 test_offtopic_corpus_real_llm.py 兜。

跑法：
    docker compose exec backend pytest tests/test_offtopic_corpus_mocked.py -v
"""
from __future__ import annotations
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.intent import TemplateSelectionOutput
from app.services.core.pipeline import (
    OffTopicIntentError,
    PipelineInput,
    pipeline_preview,
)
from tests.conftest import load_corpus_samples


def _build_input(sample: dict) -> PipelineInput:
    return PipelineInput(
        original_intent=sample["input"],
        code_type=sample["code_type"],
        clk="clk",
        rst="rst_n",
        rst_polarity="低有效",
        signals=sample.get("signals") or [],
    )


def _fake_rag_candidate(template_id: str, score: float, code_type: str):
    fake_template = MagicMock()
    fake_template.parameters = []
    fake_template.id = template_id
    fake_template.name = f"Template {template_id}"
    fake_template.version = "1.0.0"
    fake_template.code_type = code_type
    return {
        "template_id": template_id,
        "name": f"Template {template_id}",
        "description": f"desc-{template_id}",
        "score": score,
        "template": fake_template,
    }


def _patch_pipeline_deps(
    stack: ExitStack,
    dense_score: float,
    rag: list[dict] | None = None,
    llm_sel: TemplateSelectionOutput | None = None,
    db_return=None,
):
    """统一 patch pipeline_preview 上游。dense_score 触发 / 不触发 off-topic 闸的关键。"""
    stack.enter_context(patch(
        "app.services.core.pipeline.dense_top1_score",
        new=AsyncMock(return_value=dense_score),
    ))
    stack.enter_context(patch(
        "app.services.core.pipeline.normalize_intent",
        new=AsyncMock(return_value=("normalized text", "hash_abc")),
    ))
    stack.enter_context(patch(
        "app.services.core.pipeline.lookup_history",
        new=AsyncMock(return_value=None),
    ))
    stack.enter_context(patch(
        "app.services.core.pipeline.rag_retrieve",
        new=AsyncMock(return_value=rag or []),
    ))
    stack.enter_context(patch(
        "app.services.core.pipeline._keyword_supplement",
        new=AsyncMock(return_value=[]),
    ))
    fake_llm = MagicMock()
    fake_llm.select_template = AsyncMock(
        return_value=llm_sel or TemplateSelectionOutput(
            template_id="", param_mapping={}, confidence=0.0,
        )
    )
    stack.enter_context(patch(
        "app.services.core.pipeline.get_default_llm_client",
        new=AsyncMock(return_value=fake_llm),
    ))
    fake_db = MagicMock()
    fake_db.get = AsyncMock(return_value=db_return)
    return fake_db


# ── off_topic：dense 分数低于阈值 → 早返 OffTopicIntentError ─────────────

@pytest.mark.parametrize(
    "sample",
    load_corpus_samples("off_topic"),
    ids=lambda s: s["_pid"],
)
@pytest.mark.asyncio
async def test_offtopic_sample_blocked_by_dense_threshold(sample):
    """mock dense_top1_score 返低于阈值（0.30）→ pipeline 应当抛 OffTopicIntentError。

    阈值默认 0.44。0.30 < 0.44 触发闸。验证 pipeline 的"看到低分数 → 早返"逻辑。
    """
    with ExitStack() as stack:
        fake_db = _patch_pipeline_deps(stack, dense_score=0.30)
        with pytest.raises(OffTopicIntentError) as excinfo:
            await pipeline_preview(_build_input(sample), fake_db)
    assert excinfo.value.detector == "rag_dense_threshold"
    assert excinfo.value.top_dense_score == 0.30


# ── marginal_ic：dense 分数高于阈值 → 正常走 pipeline ──────────────────

@pytest.mark.parametrize(
    "sample",
    load_corpus_samples("marginal_ic"),
    ids=lambda s: s["_pid"],
)
@pytest.mark.asyncio
async def test_marginal_ic_sample_passes_pipeline(sample):
    """mock dense_top1_score 返高于阈值（0.70）+ mock RAG/LLM 给出合理候选 →
    pipeline 正常返 PreviewResult。"""
    ct = sample["code_type"]
    candidate_id = "sva_data_integrity_v1" if ct == "assertion" else "cov_value_coverage_v1"
    rag = [_fake_rag_candidate(candidate_id, score=0.9, code_type=ct)]
    llm_sel = TemplateSelectionOutput(
        template_id=candidate_id, param_mapping={}, confidence=0.85,
    )

    with ExitStack() as stack:
        fake_db = _patch_pipeline_deps(
            stack,
            dense_score=0.70,
            rag=rag,
            llm_sel=llm_sel,
            db_return=rag[0]["template"],
        )
        result = await pipeline_preview(_build_input(sample), fake_db)

    assert result.template_id == candidate_id
    assert result.confidence_source in {"llm_step1", "rag_fallback"}
