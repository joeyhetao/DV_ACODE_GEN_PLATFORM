"""Real-LLM 端到端回归测试：调真 pipeline_preview，验证 LLM step1 在 A4 候选渲染扩容 +
A10 differentiators / non_use_cases 加入后，能稳定挑出 correct_template 而非
confusion_template。

与 mock 套件的关心点分离：
- mock 套件：守 pipeline 路由逻辑（LLM 给对了 → pipeline 必落地）
- 本套件：守真实 LLM 分类率（GLM-4.7 + 当前 prompt + 真候选 description）

跑法（默认跳过；需显式 flag）：
    docker compose exec backend pytest tests/test_template_confusion_corpus_real_llm.py --real-llm -v

前置：
    - llm_configs 表有 is_default=true 的配置
    - embedding_service 健康
    - Qdrant 已 import 全部 10 个模板

成本：每条 case 跑完整 pipeline (~3-8s)，10 条 ≈ 30-80s。
"""
from __future__ import annotations
import warnings

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.llm_config import LLMConfig
from app.services.core.pipeline import (
    NoMatchingTemplateError,
    PipelineInput,
    UnderSpecifiedIntentError,
    pipeline_preview,
)
from tests.conftest import load_confusion_corpus_cases


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


def _build_input(case: dict) -> PipelineInput:
    return PipelineInput(
        original_intent=case["input"],
        code_type=case["code_type"],
        clk="clk",
        rst="rst_n",
        rst_polarity="低有效",
        signals=case.get("signals") or [],
    )


@pytest.mark.real_llm
@pytest.mark.parametrize(
    "case",
    load_confusion_corpus_cases("confusion_pairs"),
    ids=lambda c: c["_pid"],
)
@pytest.mark.asyncio
async def test_confusion_pair_real_e2e_selects_correct(case: dict) -> None:
    """对每条 confusion case：调真 pipeline_preview，断言 template_id == correct_template。

    容错策略：
      - UnderSpecifiedIntentError：算"路由对了但参数缺"，仍校验 e.template_id == correct
        （signals 没给全是 case 数据限制，不是 step1 错；放过）。
      - NoMatchingTemplateError：算 step1 误把所有候选都拒了，这是真实 bug → fail。
      - 任何其他异常 / template_id != correct → fail，且日志打印 confusion / correct
        让人能直接看出 RAG 把哪个推上 top-1、LLM 又被它带偏到哪。

    flaky 字段：标 flaky=true 的 case 失败只 warn 不 fail，留作"已知不稳定但保留作为
    回归监视"用。
    """
    correct = case["correct_template"]
    confusion = case["confusion_template"]
    flaky = case.get("flaky", False)

    async with AsyncSessionLocal() as db:
        try:
            result = await pipeline_preview(_build_input(case), db)
        except UnderSpecifiedIntentError as e:
            # 路由层面已选中，只是参数缺；视为 step1 正确（路由测试目标已达成）
            if e.template_id == correct:
                return
            _maybe_fail(
                flaky,
                f"[{case['_pid']}] under_specified 但 template_id={e.template_id!r} "
                f"不是 correct={correct!r}（confusion={confusion!r}）",
            )
            return
        except NoMatchingTemplateError:
            _maybe_fail(
                flaky,
                f"[{case['_pid']}] 真 pipeline 抛 NoMatchingTemplate —— LLM step1 把"
                f" correct={correct!r} 也拒了，confusion={confusion!r}\n"
                f"intent: {case['input']!r}",
            )
            return
        except Exception as e:
            _maybe_fail(
                flaky,
                f"[{case['_pid']}] 真 pipeline 抛意外异常 {type(e).__name__}: {e}\n"
                f"intent: {case['input']!r}",
            )
            return

    if result.template_id == correct:
        return

    msg = (
        f"[{case['_pid']}] step1 误判：\n"
        f"  intent      : {case['input']!r}\n"
        f"  expected    : {correct!r}\n"
        f"  got         : {result.template_id!r}\n"
        f"  confusion   : {confusion!r}（注：本字段是已知最易混的近邻 id）\n"
        f"  confidence  : {result.confidence}\n"
        f"  conf_source : {result.confidence_source}\n"
        f"  rag_topN    : {[(c['template_id'], c['score']) for c in result.rag_candidates]}\n"
        f"reason from yaml: {case.get('reason')}"
    )
    _maybe_fail(flaky, msg)


def _maybe_fail(flaky: bool, msg: str) -> None:
    if flaky:
        warnings.warn(f"[flaky] {msg}")
    else:
        pytest.fail(msg)
