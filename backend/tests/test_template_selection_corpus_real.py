"""Real-embedding 回归测试：验证 RAG 检索对 template_selection_corpus.yaml 每条语料的 top-1 结果。

跟 mock 套件的关心点分离：
- mock 套件：守 pipeline 路由逻辑（mock RAG + mock LLM）
- 本套件：守 bge-m3 + Qdrant 的实际排名（正确模板必须在 top-1）

跑法（默认跳过；需显式 flag）：
    docker compose exec backend pytest tests/test_template_selection_corpus_real.py --real-embedding -v

前置条件：
    - embedding_service 健康（bge-m3 已加载）
    - Qdrant 已 import 全部模板（lib_manager.py import）
    - 修复了 keywords/description 的模板已通过 lib_manager.py rebuild 重新 embed

成本：~2-5s per case（每条意图走 stage1+stage3 检索）。
"""
from __future__ import annotations

import pytest

from app.core.database import AsyncSessionLocal
from app.services.rag.engine import rag_retrieve
from tests.conftest import load_template_corpus_cases


@pytest.mark.real_embedding
@pytest.mark.parametrize(
    "case",
    load_template_corpus_cases("correct_mapping"),
    ids=lambda c: c["_pid"],
)
@pytest.mark.asyncio
async def test_correct_template_in_top1_real_rag(case: dict) -> None:
    """真实 Qdrant + bge-m3：检索意图，断言 expected_template 在 top-1。

    若 RAG top-1 不是 expected_template，说明 embedding 空间出现了语义竞争，需要：
    1. 检查 expected_template 的 keywords/description 是否覆盖了该意图的关键语义
    2. 更新 YAML → lib_manager.py import → lib_manager.py rebuild 重新 embed
    3. 重跑本测试确认修复
    """
    async with AsyncSessionLocal() as db:
        results = await rag_retrieve(case["intent"], db, code_type=case["code_type"])

    assert results, (
        f"意图 [{case['intent']!r}] 的 RAG 返回为空——"
        "请检查 Qdrant 是否已导入模板、embedding_service 是否健康"
    )

    top1_id = results[0]["template_id"]
    assert top1_id == case["expected_template"], (
        f"意图 [{case['intent']!r}]\n"
        f"  期望 top-1: {case['expected_template']}\n"
        f"  实际 top-1: {top1_id}（score={results[0]['score']:.4f}）\n"
        f"  top-3: {[(r['template_id'], round(r['score'], 4)) for r in results[:3]]}\n"
        f"  修复方向: 检查 {case['expected_template']} 的 description/keywords 是否覆盖该意图语义"
    )
