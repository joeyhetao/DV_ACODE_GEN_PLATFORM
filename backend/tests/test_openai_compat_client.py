"""锁定 OpenAICompatLLMClient 的 thinking-mode / max_tokens 契约。

GLM-4.7 是 thinking 模型，会消耗大量 reasoning_tokens。这套 commit 明确选择：
- normalize_intent + _step1_select_id 禁 thinking（extra_body）
- _step2_fill_params 保留 thinking 用于 FSM/bins 推理

任何回归（误删 extra_body、误改 max_tokens）会立刻失败。
"""
from __future__ import annotations
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.llm.openai_compat_client import OpenAICompatLLMClient


def _make_resp(content: str = "ok"):
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = content
    resp.choices[0].finish_reason = "stop"
    return resp


def _make_client():
    with patch("openai.AsyncOpenAI"):
        client = OpenAICompatLLMClient(
            api_key="sk-test",
            model_id="glm-4.7",
            base_url="https://open.bigmodel.cn/api/paas/v4",
        )
    return client


@pytest.mark.asyncio
async def test_normalize_intent_disables_thinking_and_caps_max_tokens():
    client = _make_client()
    client._client = MagicMock()
    client._client.chat.completions.create = AsyncMock(return_value=_make_resp("normalized text"))

    await client.normalize_intent("原始意图", rules="规则1\n规则2")

    kwargs = client._client.chat.completions.create.call_args.kwargs
    assert kwargs["extra_body"] == {"thinking": {"type": "disabled"}}
    assert kwargs["max_tokens"] == 512


@pytest.mark.asyncio
async def test_step1_select_id_disables_thinking_and_caps_max_tokens():
    client = _make_client()
    client._client = MagicMock()
    client._client.chat.completions.create = AsyncMock(return_value=_make_resp("tpl_fsm_basic"))

    candidates = [
        {"template_id": "tpl_fsm_basic", "name": "FSM", "description": "状态机基础断言"},
        {"template_id": "tpl_handshake", "name": "Handshake", "description": "握手协议"},
    ]
    await client._step1_select_id("FSM 状态转换", candidates)

    kwargs = client._client.chat.completions.create.call_args.kwargs
    assert kwargs["extra_body"] == {"thinking": {"type": "disabled"}}
    assert kwargs["max_tokens"] == 64


@pytest.mark.asyncio
async def test_step2_fill_params_keeps_thinking_and_caps_max_tokens():
    client = _make_client()
    client._client = MagicMock()
    client._client.chat.completions.create = AsyncMock(
        return_value=_make_resp('{"group_name":"cur_state","signal":"cur_state","signal_width":"3"}')
    )

    required = [
        {"name": "group_name", "description": "分组名", "type": "string"},
        {"name": "signal", "description": "信号名", "type": "string"},
    ]
    await client._step2_fill_params(
        intent="对 cur_state 做状态覆盖率",
        signal_context="clk=clk rst=rst_n",
        template_id="tpl_fsm",
        required_params=required,
    )

    kwargs = client._client.chat.completions.create.call_args.kwargs
    assert "extra_body" not in kwargs, "Step2 必须保留 thinking，不应传 extra_body 禁用"
    assert kwargs["max_tokens"] == 1024


@pytest.mark.asyncio
async def test_step1_returns_empty_when_id_not_in_candidates():
    """边界：LLM 返回的 id 不在候选里 → 返回空串让 pipeline 走 RAG fallback。"""
    client = _make_client()
    client._client = MagicMock()
    client._client.chat.completions.create = AsyncMock(return_value=_make_resp("totally_unknown_id"))

    out = await client._step1_select_id(
        "意图",
        [{"template_id": "tpl_a", "name": "A", "description": "x"}],
    )
    assert out == ""
