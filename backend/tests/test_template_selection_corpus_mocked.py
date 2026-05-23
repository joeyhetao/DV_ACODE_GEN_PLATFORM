"""Mock 模式回归测试：验证 pipeline_preview 对 template_selection_corpus.yaml 每条语料的模板选择。

测试目标：当 RAG 已返回正确模板作为 top-1 候选时，LLM step1 + pipeline 路由能选中
expected_template。不测 bge-m3 embedding 准确性（由 test_template_selection_corpus_real.py 负责）。

跑法：
    docker compose exec backend pytest tests/test_template_selection_corpus_mocked.py -v
"""
from __future__ import annotations
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.intent import TemplateSelectionOutput
from app.services.core.pipeline import PipelineInput, PreviewResult, pipeline_preview
from tests.conftest import load_template_corpus_cases

# 最近邻映射：每个模板对应语义最接近的竞争者（用于构造干扰 RAG 候选）
_NEAREST_NEIGHBOR: dict[str, str] = {
    "sva_reset_behavior_v1": "sva_fsm_state_transition_v1",
    "sva_fsm_state_transition_v1": "sva_reset_behavior_v1",
    "sva_data_integrity_v1": "sva_handshake_stable_v1",
    "sva_handshake_stable_v1": "sva_handshake_timeout_v1",
    "sva_handshake_timeout_v1": "sva_handshake_stable_v1",
    "sva_timing_max_delay_v1": "sva_handshake_timeout_v1",
    "cov_value_coverage_v1": "cov_transition_coverage_v1",
    "cov_transition_coverage_v1": "cov_value_coverage_v1",
    "cov_protocol_handshake_v1": "cov_transition_coverage_v1",
    "cov_cross_coverage_v1": "cov_transition_coverage_v1",
}

_FALLBACK_NEIGHBOR = "sva_data_integrity_v1"


def _nearest_neighbor(template_id: str) -> str:
    return _NEAREST_NEIGHBOR.get(template_id, _FALLBACK_NEIGHBOR)


def _fake_candidate(template_id: str, score: float, code_type: str = "assertion") -> dict:
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
    rag: list[dict],
    llm_sel: TemplateSelectionOutput,
    db_return=None,
) -> MagicMock:
    """统一 patch pipeline_preview 所有上游依赖。dense_score 固定高分（0.85），不触发 off-topic 闸。"""
    stack.enter_context(patch(
        "app.services.core.pipeline.dense_top1_score",
        new=AsyncMock(return_value=0.85),
    ))
    stack.enter_context(patch(
        "app.services.core.pipeline.normalize_intent",
        new=AsyncMock(return_value=("normalized intent", "hash_abc")),
    ))
    stack.enter_context(patch(
        "app.services.core.pipeline.lookup_history",
        new=AsyncMock(return_value=None),
    ))
    stack.enter_context(patch(
        "app.services.core.pipeline.rag_retrieve",
        new=AsyncMock(return_value=rag),
    ))
    stack.enter_context(patch(
        "app.services.core.pipeline._keyword_supplement",
        new=AsyncMock(return_value=[]),
    ))
    fake_llm = MagicMock()
    fake_llm.select_template = AsyncMock(return_value=llm_sel)
    fake_llm.config_id = ""
    stack.enter_context(patch(
        "app.services.core.pipeline.get_default_llm_client",
        new=AsyncMock(return_value=fake_llm),
    ))
    fake_db = MagicMock()
    fake_db.get = AsyncMock(return_value=db_return if db_return is not None else rag[0]["template"])
    return fake_db


def _build_input(case: dict) -> PipelineInput:
    return PipelineInput(
        original_intent=case["intent"],
        code_type=case["code_type"],
        clk="clk",
        rst="rst_n",
        rst_polarity="低有效",
        signals=[],
    )


@pytest.mark.parametrize(
    "case",
    load_template_corpus_cases("correct_mapping"),
    ids=lambda c: c["_pid"],
)
@pytest.mark.asyncio
async def test_correct_template_selected_mocked(case: dict) -> None:
    """mock RAG 返回正确模板 top-1（score=0.85）+ 2 个语义近邻干扰候选；
    mock LLM 选中正确模板；断言 pipeline 路由到 expected_template。

    测的是 pipeline 路由逻辑，不是 RAG embedding 准确性。
    """
    expected = case["expected_template"]
    code_type = case["code_type"]
    neighbor = _nearest_neighbor(expected)
    third = "sva_data_integrity_v1" if expected != "sva_data_integrity_v1" else "sva_handshake_stable_v1"

    rag = [
        _fake_candidate(expected, score=0.85, code_type=code_type),
        _fake_candidate(neighbor, score=0.72, code_type=code_type),
        _fake_candidate(third, score=0.60, code_type=code_type),
    ]
    llm_sel = TemplateSelectionOutput(
        template_id=expected,
        param_mapping={},
        confidence=0.9,
    )

    with ExitStack() as stack:
        fake_db = _patch_pipeline_deps(stack, rag=rag, llm_sel=llm_sel)
        result: PreviewResult = await pipeline_preview(_build_input(case), fake_db)

    assert result.template_id == expected, (
        f"意图 [{case['intent']!r}] 期望模板 {expected!r}，"
        f"实际 pipeline 路由到 {result.template_id!r}"
    )
    assert result.confidence_source in {"llm_step1", "rag_fallback", "keyword_supplement"}
