"""Mock 模式回归测试：验证近邻混淆对场景下 pipeline_preview 仍能选中 correct_template。

测试目标：当 RAG 把 confusion_template 当作 top-1（最不利干扰环境），且 LLM step1
mock 也回 correct_template（模拟 A4 候选渲染扩容 + A10 differentiators 后 LLM 能
区分），pipeline 应该最终路由到 correct_template，而非被 RAG top-1 fallback 拖到
confusion_template。

测试覆盖（A12）：
  - pair-A: handshake_stable ↔ handshake_timeout × 4
  - pair-B: timing_max_delay ↔ handshake_timeout × 4
  - FSM 类: fsm_state_transition ↔ reset_behavior × 1
  - coverage 类: cov_transition_coverage ↔ cov_value_coverage × 1

每条 case 同时验证两个方向：
  正向: RAG top-1 = confusion_template, LLM 选 correct → pipeline 必选 correct
  反向（保留为未来扩展）: 若 LLM 也选错，pipeline 通过 A8 verify 把它降级 ——
  当前 mock 套件只锁正向契约，反向由 real-llm 套件去暴露。

跑法（容器内）:
    docker compose exec backend pytest tests/test_template_confusion_corpus_mocked.py -v
"""
from __future__ import annotations
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.intent import TemplateSelectionOutput
from app.services.core.pipeline import PipelineInput, PreviewResult, pipeline_preview
from tests.conftest import load_confusion_corpus_cases


def _fake_template(template_id: str, code_type: str, parameters: list[dict] | None = None) -> MagicMock:
    t = MagicMock()
    t.id = template_id
    t.name = f"Template {template_id}"
    t.version = "1.0.0"
    t.code_type = code_type
    t.parameters = parameters or []
    return t


def _fake_candidate(template_id: str, score: float, code_type: str) -> dict:
    return {
        "template_id": template_id,
        "name": f"Template {template_id}",
        "description": f"desc-{template_id}",
        "score": score,
        "template": _fake_template(template_id, code_type),
    }


def _patch_pipeline_for_confusion(
    stack: ExitStack,
    rag_candidates: list[dict],
    llm_pick: TemplateSelectionOutput,
    correct_template: MagicMock,
) -> MagicMock:
    """Patch pipeline_preview 所有上游依赖。

    dense_top1_score 固定 0.9（高于阈值）避免触发 off-topic 闸。
    db.get 按 template_id 返回对应 fake template；其余 id 返 None。
    """
    stack.enter_context(patch(
        "app.services.core.pipeline.dense_top1_score",
        new=AsyncMock(return_value=0.9),
    ))
    stack.enter_context(patch(
        "app.services.core.pipeline.normalize_intent",
        new=AsyncMock(return_value=("normalized intent", "hash_conf")),
    ))
    stack.enter_context(patch(
        "app.services.core.pipeline.lookup_history",
        new=AsyncMock(return_value=None),
    ))
    stack.enter_context(patch(
        "app.services.core.pipeline.rag_retrieve",
        new=AsyncMock(return_value=rag_candidates),
    ))
    stack.enter_context(patch(
        "app.services.core.pipeline._keyword_supplement",
        new=AsyncMock(return_value=[]),
    ))
    fake_llm = MagicMock()
    fake_llm.select_template = AsyncMock(return_value=llm_pick)
    fake_llm.config_id = ""
    # A8 verify_step1_selection：mock 套件假设 LLM 选对了就 verify 通过
    fake_llm.verify_step1_selection = AsyncMock(return_value=True)
    stack.enter_context(patch(
        "app.services.core.pipeline.get_default_llm_client",
        new=AsyncMock(return_value=fake_llm),
    ))

    # rag_candidates 里的每个模板都得能 db.get 到（pipeline 用 db.get(Template, id)
    # 拿真模板拼 PreviewResult）。按 id 查表。
    id_to_tmpl = {c["template_id"]: c["template"] for c in rag_candidates}

    async def _db_get(model, id_):
        return id_to_tmpl.get(id_)

    fake_db = MagicMock()
    fake_db.get = AsyncMock(side_effect=_db_get)
    return fake_db


def _build_input(case: dict) -> PipelineInput:
    return PipelineInput(
        original_intent=case["input"],
        code_type=case["code_type"],
        clk="clk",
        rst="rst_n",
        rst_polarity="低有效",
        signals=case.get("signals") or [],
    )


@pytest.mark.parametrize(
    "case",
    load_confusion_corpus_cases("confusion_pairs"),
    ids=lambda c: c["_pid"],
)
@pytest.mark.asyncio
async def test_pipeline_picks_correct_under_confusion_top1(case: dict) -> None:
    """混淆对核心断言：RAG 把 confusion_template 当 top-1，但 LLM step1 选中
    correct_template → pipeline 必须落地到 correct，而不被 rag_fallback 拖走。

    构造：
      - rag[0] = confusion_template (score=0.85，作为 RAG 误判 top-1)
      - rag[1] = correct_template   (score=0.72)
      - LLM mock 返 correct_template
    断言：result.template_id == correct, confidence_source != rag_fallback
    """
    correct = case["correct_template"]
    confusion = case["confusion_template"]
    code_type = case["code_type"]

    correct_tmpl = _fake_template(correct, code_type)

    rag = [
        _fake_candidate(confusion, score=0.85, code_type=code_type),
        _fake_candidate(correct, score=0.72, code_type=code_type),
    ]
    # 让 rag[1] 的 template 指针正好是我们 db.get 会返回的对象
    rag[1]["template"] = correct_tmpl

    llm_pick = TemplateSelectionOutput(
        template_id=correct,
        param_mapping={},
        confidence=0.9,
    )

    with ExitStack() as stack:
        fake_db = _patch_pipeline_for_confusion(stack, rag, llm_pick, correct_tmpl)
        # 关掉 under_specified gate：本套件只验证 step1 路由契约；参数完整性由其它
        # 套件覆盖（confusion case 的 signals 列表不一定覆盖模板所有 required 参数）。
        from app.core.config import get_settings
        settings = get_settings()
        orig_us = settings.under_specified_gate_enabled
        orig_rg = settings.step1_reranker_gate_enabled if hasattr(settings, "step1_reranker_gate_enabled") else None
        settings.under_specified_gate_enabled = False
        if orig_rg is not None:
            # A9 reranker gate 关掉：本套件构造的 rag[1].score=0.72 高于默认阈值，
            # 但保险起见关闭隔离测试目标。
            settings.step1_reranker_gate_enabled = False
        try:
            result: PreviewResult = await pipeline_preview(_build_input(case), fake_db)
        finally:
            settings.under_specified_gate_enabled = orig_us
            if orig_rg is not None:
                settings.step1_reranker_gate_enabled = orig_rg

    assert result.template_id == correct, (
        f"[{case['_pid']}] 期望 pipeline 选中 correct={correct!r}，"
        f"实际选中 {result.template_id!r}（confusion={confusion!r}）。"
        f"\nintent: {case['input']!r}"
    )
    assert result.confidence_source in {"llm_step1", "keyword_supplement"}, (
        f"[{case['_pid']}] 期望 confidence_source 为 llm_step1（LLM 选中即生效），"
        f"实际 {result.confidence_source!r} —— 若为 rag_fallback 说明 LLM 选择被丢弃"
    )
