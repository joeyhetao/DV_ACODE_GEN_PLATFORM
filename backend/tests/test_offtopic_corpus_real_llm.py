"""Real-LLM 端到端回归测试：直接调真 pipeline_preview，验证 off-topic 闸 + RAG/LLM 路径。

跟 mock 套件的关心点分离：
- mock 套件：守 pipeline 逻辑分支（看到低分数→早返；看到高分数→正常走）
- 本套件：守端到端行为（bge-m3 dense embedding + 阈值 0.44 + RAG/LLM 三阶段）

跑法（默认跳过；需显式 flag）：
    docker compose exec backend pytest tests/test_offtopic_corpus_real_llm.py --real-llm -v

前置条件：
    - `llm_configs` 表里有一条 `is_default=true` 的 LLMConfig
    - embedding_service 健康
    - Qdrant 已 import 模板

成本：~30-60s per run（off_topic 只走 dense gate ~50ms 一条；marginal_ic 跑完整 pipeline）。
"""
from __future__ import annotations
import warnings

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.llm_config import LLMConfig
from app.services.core.pipeline import (
    OffTopicIntentError,
    PipelineInput,
    pipeline_preview,
)
from tests.conftest import load_corpus_samples


@pytest.fixture(scope="session", autouse=True)
async def _require_default_llm_config():
    """整套 real-LLM 测开跑前确认 llm_configs 表有 is_default=true 的记录；否则全 skip。"""
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(LLMConfig).where(LLMConfig.is_default.is_(True)))
        if result.scalar_one_or_none() is None:
            pytest.skip(
                "real-LLM 测试需要 llm_configs 表预填一条 is_default=true 的配置。"
                "请通过 Admin UI（/admin/llm）添加。"
            )


def _build_input(sample: dict) -> PipelineInput:
    return PipelineInput(
        original_intent=sample["input"],
        code_type=sample["code_type"],
        clk="clk",
        rst="rst_n",
        rst_polarity="低有效",
        signals=sample.get("signals") or [],
    )


@pytest.mark.real_llm
@pytest.mark.parametrize(
    "sample",
    load_corpus_samples("off_topic"),
    ids=lambda s: s["_pid"],
)
@pytest.mark.asyncio
async def test_offtopic_real_e2e_rejected(sample):
    """无关意图：pipeline_preview 应抛 OffTopicIntentError（dense 阈值闸）。"""
    async with AsyncSessionLocal() as db:
        if sample.get("flaky"):
            try:
                await pipeline_preview(_build_input(sample), db)
                warnings.warn(
                    f"[flaky] off_topic sample {sample['_pid']} 未被 dense gate 拦下"
                )
            except OffTopicIntentError:
                pass
            return
        with pytest.raises(OffTopicIntentError) as excinfo:
            await pipeline_preview(_build_input(sample), db)
        assert excinfo.value.detector == "rag_dense_threshold"


@pytest.mark.real_llm
@pytest.mark.parametrize(
    "sample",
    load_corpus_samples("marginal_ic"),
    ids=lambda s: s["_pid"],
)
@pytest.mark.asyncio
async def test_marginal_ic_real_e2e_passes(sample):
    """marginal 真请求：pipeline_preview 应正常返 PreviewResult（不抛 OffTopicIntentError）。"""
    async with AsyncSessionLocal() as db:
        try:
            result = await pipeline_preview(_build_input(sample), db)
        except OffTopicIntentError as e:
            if sample.get("flaky"):
                warnings.warn(
                    f"[flaky] marginal_ic sample {sample['_pid']} 被误拒；"
                    f"top_dense={e.top_dense_score:.4f}"
                )
                return
            pytest.fail(
                f"marginal_ic sample {sample['_pid']} 被 dense gate 误拒。\n"
                f"  input: {sample['input']!r}\n"
                f"  top_dense_score: {e.top_dense_score:.4f}\n"
                f"  threshold: {e.threshold}\n"
                f"  → 阈值需下调，或样本不再典型，考虑加 flaky: true"
            )
    assert result.template_id  # 选到了某个模板
    assert result.confidence_source in {"llm_step1", "rag_fallback", "intent_cache"}
