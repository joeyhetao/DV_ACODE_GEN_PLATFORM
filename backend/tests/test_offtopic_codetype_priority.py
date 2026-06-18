"""FEAT-15: off-topic 与 code_type_mismatch 闸协同的优先级单测。

四个场景验证 gate 1/2 共享一次 cross-code-type dense 扫描后的路由：
  1. selected 子集低分但 other 高分 → CodeTypeMismatchError（不是 OffTopicIntentError）
  2. 全库低分 → OffTopicIntentError（不是 CodeTypeMismatchError）
  3. best_overall ≥ 阈值且 gap < margin → 两闸都不触发，pipeline 正常继续
  4. selected 子集低分 + other 略高但仍 < 阈值 → OffTopicIntentError（即便 gap ≥ margin）

跑法：
    docker compose exec backend pytest tests/test_offtopic_codetype_priority.py -v
"""
from __future__ import annotations
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.intent import TemplateSelectionOutput
from app.services.core.pipeline import (
    CodeTypeMismatchError,
    OffTopicIntentError,
    PipelineInput,
    pipeline_preview,
)


def _make_inp(code_type: str = "assertion", text: str = "some user input") -> PipelineInput:
    return PipelineInput(
        original_intent=text,
        code_type=code_type,
        clk="clk",
        rst="rst_n",
        rst_polarity="低有效",
        signals=[],
    )


def _patch_dense_per_code_type(stack: ExitStack, scores: dict[str, float]) -> None:
    """让 dense_top1_score 按 code_type kwarg 返不同分数。未列出的类型默认 0.0。"""
    async def fake(query_text, code_type=None):
        return scores.get(code_type, 0.0)
    stack.enter_context(patch("app.services.core.pipeline.dense_top1_score", new=fake))


def _patch_downstream_to_let_pipeline_finish(stack: ExitStack) -> MagicMock:
    """两闸都不触发的场景下，mock 下游让 pipeline_preview 能跑到返回 PreviewResult。"""
    fake_tmpl = MagicMock()
    fake_tmpl.parameters = []
    fake_tmpl.id = "sva_pass_through_v1"
    fake_tmpl.name = "pass-through"
    fake_tmpl.version = "1.0.0"

    fake_rag_tmpl = MagicMock()
    fake_rag_tmpl.parameters = []
    rag = [{
        "template_id": "sva_pass_through_v1",
        "name": "pass-through",
        "description": "desc",
        "score": 0.9,
        "template": fake_rag_tmpl,
    }]

    stack.enter_context(patch(
        "app.services.core.pipeline.normalize_intent",
        new=AsyncMock(return_value=("normalized", "h_border")),
    ))
    stack.enter_context(patch(
        "app.services.core.pipeline.lookup_history", new=AsyncMock(return_value=None),
    ))
    stack.enter_context(patch(
        "app.services.core.pipeline.rag_retrieve", new=AsyncMock(return_value=rag),
    ))
    stack.enter_context(patch(
        "app.services.core.pipeline._keyword_supplement", new=AsyncMock(return_value=[]),
    ))
    fake_llm = MagicMock()
    fake_llm.select_template = AsyncMock(return_value=TemplateSelectionOutput(
        template_id="sva_pass_through_v1", param_mapping={}, confidence=0.8,
    ))
    fake_llm.verify_step1_selection = AsyncMock(return_value=True)
    stack.enter_context(patch(
        "app.services.core.pipeline.get_default_llm_client",
        new=AsyncMock(return_value=fake_llm),
    ))
    fake_db = MagicMock()
    fake_db.get = AsyncMock(return_value=fake_tmpl)
    return fake_db


# ── 场景 1：错选 code_type 真请求 → mismatch 优先 ──────────────────────

@pytest.mark.asyncio
async def test_cross_code_type_mismatch_routes_to_mismatch_not_offtopic():
    """选 assertion，但意图实际属于 coverage（assertion=0.41 / coverage=0.76）。

    老逻辑会因 selected_dense=0.41 < 0.44 早返 OffTopicIntentError，误判为非 IC 请求。
    新逻辑 best_overall=0.76 ≥ 阈值，gate 1 跳过；gate 2 看 gap=0.35 ≥ margin 且
    best_other=0.76 ≥ 阈值 → CodeTypeMismatchError 引导用户改用 coverage。
    """
    with ExitStack() as stack:
        _patch_dense_per_code_type(stack, {"assertion": 0.41, "coverage": 0.76})
        with pytest.raises(CodeTypeMismatchError) as excinfo:
            await pipeline_preview(_make_inp(code_type="assertion"), MagicMock())

    e = excinfo.value
    assert e.selected_code_type == "assertion"
    assert e.suggested_code_type == "coverage"
    assert abs(e.selected_score - 0.41) < 1e-6
    assert abs(e.suggested_score - 0.76) < 1e-6
    assert e.detector == "rag_dense_cross_code_type"


# ── 场景 2：全库低分 → off-topic ────────────────────────────────────

@pytest.mark.asyncio
async def test_truly_offtopic_all_low_routes_to_offtopic():
    """所有 code_type 子集 dense 均 < 阈值 → 真正的非 IC 输入。"""
    with ExitStack() as stack:
        _patch_dense_per_code_type(stack, {"assertion": 0.30, "coverage": 0.30})
        with pytest.raises(OffTopicIntentError) as excinfo:
            await pipeline_preview(_make_inp(code_type="assertion"), MagicMock())

    e = excinfo.value
    assert e.detector == "rag_dense_threshold"
    # top_dense_score 现在传的是 best_overall（全库最高分），与前端 Modal 文案
    # "输入与模板库的最高相似度" 语义一致。这里 best_overall = max(0.30, 0.30) = 0.30。
    assert abs(e.top_dense_score - 0.30) < 1e-6
    assert e.threshold == 0.44


# ── 场景 3：边界过线 / gap 小 → 两闸都不触发，继续 ──────────────────

@pytest.mark.asyncio
async def test_borderline_overall_above_threshold_gap_below_margin_passes():
    """selected=0.43 / other=0.45 → best_overall=0.45 ≥ 0.44；gap=0.02 < 0.10。

    边界 in-domain + 类型差距不显著 → 两闸都不抛，pipeline 走完正常路径返 PreviewResult。
    """
    with ExitStack() as stack:
        _patch_dense_per_code_type(stack, {"assertion": 0.43, "coverage": 0.45})
        fake_db = _patch_downstream_to_let_pipeline_finish(stack)
        result = await pipeline_preview(_make_inp(code_type="assertion"), fake_db)

    assert result.template_id == "sva_pass_through_v1"


# ── 场景 4：other 略高但全库仍低 → off-topic（不是 mismatch）─────────

@pytest.mark.asyncio
async def test_best_other_below_threshold_does_not_trigger_mismatch_even_with_gap():
    """selected=0.30 / other=0.42 → best_overall=0.42 < 0.44，全库都没"有把握"。

    即使 gap=0.12 ≥ margin，best_other 自身没过 in-domain 阈值，不能给"换类"建议——
    这才是真正的 off-topic。验证 gate 2 的 `best_other_score >= threshold` 前置条件。
    """
    with ExitStack() as stack:
        _patch_dense_per_code_type(stack, {"assertion": 0.30, "coverage": 0.42})
        with pytest.raises(OffTopicIntentError) as excinfo:
            await pipeline_preview(_make_inp(code_type="assertion"), MagicMock())

    e = excinfo.value
    assert e.detector == "rag_dense_threshold"
    assert abs(e.top_dense_score - 0.42) < 1e-6
