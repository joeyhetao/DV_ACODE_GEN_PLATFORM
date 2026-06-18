"""FEAT-14 step1 数字兜底契约测试。

锁定两个 client 在 LLM raw 返回序号字符串（如 '3'、'3.'、' 3 '、'"3"'）时，能够
正确映射到 candidates[N-1]['template_id']，使 pipeline 看到合法 id 而不再误触发
no_matching_template 闸。

边界：
- N=0 / N=len(candidates)+1 / 非数字字符串 / 完整合法 id / 完整非法 id
- AnthropicClient tool calling 同等兜底（return string '3' 时映射）

跑法：
    docker compose exec backend pytest tests/test_step1_numeric_fallback.py -v
"""
from __future__ import annotations
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.llm.openai_compat_client import OpenAICompatLLMClient
from app.services.llm.anthropic_client import AnthropicLLMClient


# ── 共享 fixture ────────────────────────────────────────────────────────────

_CANDIDATES = [
    {"template_id": "sva_fsm_transition_v1", "name": "FSM Transition", "description": "FSM 转换断言"},
    {"template_id": "sva_handshake_stable_v1", "name": "Handshake Stable", "description": "握手稳定性"},
    {"template_id": "sva_handshake_timeout_v1", "name": "Handshake Timeout", "description": "握手超时检测"},
]


def _make_openai_resp(content: str):
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = content
    resp.choices[0].finish_reason = "stop"
    return resp


def _make_openai_client():
    with patch("openai.AsyncOpenAI"):
        client = OpenAICompatLLMClient(
            api_key="sk-test",
            model_id="glm-4.7",
            base_url="https://open.bigmodel.cn/api/paas/v4",
        )
    client._client = MagicMock()
    return client


# ── OpenAICompat _step1_select_id 数字兜底 ─────────────────────────────────

@pytest.mark.parametrize(
    "raw_content,expected_id",
    [
        # 裸数字 → 第 N 个候选
        ("3", "sva_handshake_timeout_v1"),
        # 带尾部句号
        ("3.", "sva_handshake_timeout_v1"),
        # 带前后空白
        (" 3 ", "sva_handshake_timeout_v1"),
        # 带双引号包裹
        ('"3"', "sva_handshake_timeout_v1"),
        # 带单引号包裹
        ("'3'", "sva_handshake_timeout_v1"),
        # 带尾部换行（_step1_select_id 顶层 .strip() 会处理 → 兜底应命中）
        ("3\n\n", "sva_handshake_timeout_v1"),
        # 首行空行后跟数字（同上，顶层 .strip() 处理）
        ("\n3\n", "sva_handshake_timeout_v1"),
        # 第 1 / 第 2 候选
        ("1", "sva_fsm_transition_v1"),
        ("2", "sva_handshake_stable_v1"),
    ],
)
@pytest.mark.asyncio
async def test_openai_step1_numeric_fallback_resolves_to_template_id(raw_content, expected_id):
    """LLM 返序号字符串（含修饰）应映射到 candidates[N-1].template_id。"""
    client = _make_openai_client()
    client._client.chat.completions.create = AsyncMock(return_value=_make_openai_resp(raw_content))

    out = await client._step1_select_id("AXI 握手超时检测", _CANDIDATES)
    assert out == expected_id


@pytest.mark.parametrize(
    "raw_content",
    [
        # 越界数字
        "0",
        "4",
        "99",
        # 非 ascii 数字（中文一二三不算）
        "三",
        # 纯文本
        "none",
        "totally_unknown_template_v999",
        # 空串
        "",
        # 数字 + 尾部噪声（实测 GLM-4.7 偶发形态："我选第 3 个" / "3 (我选的)"）
        # 顶层 .strip() 处理不了内部噪声，isdigit() 应为 False
        "3 (我选的)",
        "3 because of XX",
        # 中文序号——不应被误识别
        "第3个",
        "选 3",
    ],
)
@pytest.mark.asyncio
async def test_openai_step1_numeric_fallback_returns_empty_on_invalid(raw_content):
    """N=0 / N>len(candidates) / 非数字 / 'none' / 越权非法 id / 数字+噪声 都应返回空串。"""
    client = _make_openai_client()
    client._client.chat.completions.create = AsyncMock(return_value=_make_openai_resp(raw_content))

    out = await client._step1_select_id("AXI 握手超时检测", _CANDIDATES)
    assert out == ""


@pytest.mark.asyncio
async def test_openai_step1_exact_id_match_still_works():
    """精确匹配路径不受数字兜底影响：raw 含合法 template_id 直接返回。"""
    client = _make_openai_client()
    client._client.chat.completions.create = AsyncMock(
        return_value=_make_openai_resp("sva_handshake_timeout_v1")
    )

    out = await client._step1_select_id("AXI 握手超时检测", _CANDIDATES)
    assert out == "sva_handshake_timeout_v1"


@pytest.mark.asyncio
async def test_openai_step1_exact_id_takes_precedence_over_numeric():
    """raw 同时含合法 id 和数字时优先精确匹配（_render 顺序无关）。"""
    client = _make_openai_client()
    # raw 既含 id 也含 '3'，精确匹配应胜出
    client._client.chat.completions.create = AsyncMock(
        return_value=_make_openai_resp("sva_fsm_transition_v1 (候选 1)")
    )

    out = await client._step1_select_id("FSM 状态转换", _CANDIDATES)
    assert out == "sva_fsm_transition_v1"


# ── AnthropicClient.select_template 数字兜底 ───────────────────────────────

def _make_anthropic_tool_block(template_id: str, param_mapping: dict | None = None, confidence: float = 0.9):
    block = MagicMock()
    block.type = "tool_use"
    block.name = "select_template"
    block.input = {
        "template_id": template_id,
        "param_mapping": param_mapping or {},
        "confidence": confidence,
    }
    return block


def _make_anthropic_msg(blocks: list):
    msg = MagicMock()
    msg.content = blocks
    msg.usage = MagicMock()
    return msg


def _make_anthropic_client():
    with patch("anthropic.AsyncAnthropic"):
        client = AnthropicLLMClient(api_key="sk-test", model_id="claude-sonnet-4-6")
    client._client = MagicMock()
    return client


@pytest.mark.parametrize(
    "tool_template_id,expected_id",
    [
        ("3", "sva_handshake_timeout_v1"),
        ("3.", "sva_handshake_timeout_v1"),
        (" 3 ", "sva_handshake_timeout_v1"),
        ('"3"', "sva_handshake_timeout_v1"),
        ("1", "sva_fsm_transition_v1"),
        # 换行变体（与 OpenAI 端对称覆盖；共用 resolve_numeric_fallback 应一致处理）
        ("3\n\n", "sva_handshake_timeout_v1"),
        ("\n3\n", "sva_handshake_timeout_v1"),
    ],
)
@pytest.mark.asyncio
async def test_anthropic_select_template_numeric_fallback(tool_template_id, expected_id):
    """Anthropic tool calling 把候选序号字符串塞进 template_id 时，应映射到 candidates[N-1]."""
    client = _make_anthropic_client()
    client._client.messages.create = AsyncMock(
        return_value=_make_anthropic_msg([_make_anthropic_tool_block(tool_template_id)])
    )

    out = await client.select_template(
        normalized_intent="AXI 握手超时检测",
        signal_context="clk=clk rst=rst_n",
        candidates=_CANDIDATES,
    )
    assert out.template_id == expected_id


@pytest.mark.asyncio
async def test_anthropic_select_template_legal_id_unchanged():
    """tool 返回合法 template_id 时走原路径，不进数字兜底分支。"""
    client = _make_anthropic_client()
    client._client.messages.create = AsyncMock(
        return_value=_make_anthropic_msg(
            [_make_anthropic_tool_block("sva_handshake_stable_v1", {"valid": "v"}, 0.95)]
        )
    )

    out = await client.select_template(
        normalized_intent="握手稳定性",
        signal_context="clk=clk",
        candidates=_CANDIDATES,
    )
    assert out.template_id == "sva_handshake_stable_v1"
    assert out.param_mapping == {"valid": "v"}
    assert out.confidence == 0.95


@pytest.mark.parametrize("tool_template_id", ["0", "4", "99", "totally_unknown_v1", ""])
@pytest.mark.asyncio
async def test_anthropic_select_template_invalid_passthrough(tool_template_id):
    """tool 返回越界数字 / 非数字非候选字符串时不解析，原样透传给 pipeline。

    透传给 pipeline 的 rag_fallback / confidence_source 链处理。
    """
    client = _make_anthropic_client()
    client._client.messages.create = AsyncMock(
        return_value=_make_anthropic_msg([_make_anthropic_tool_block(tool_template_id)])
    )

    out = await client.select_template(
        normalized_intent="X",
        signal_context="",
        candidates=_CANDIDATES,
    )
    assert out.template_id == tool_template_id


@pytest.mark.asyncio
async def test_anthropic_select_template_none_is_passthrough():
    """'none' 是合法的"无任何候选匹配"语义信号，pipeline 据此设 confidence_source='rag_fallback'
    并触发 no_matching_template 闸。必须原样透传，不能被数字兜底意外吃掉，也不能被合法
    候选 id 子串混淆。这条测试独立锁定该约定（与 invalid passthrough 区分开）。
    """
    client = _make_anthropic_client()
    client._client.messages.create = AsyncMock(
        return_value=_make_anthropic_msg([_make_anthropic_tool_block("none")])
    )

    out = await client.select_template(
        normalized_intent="完全不相关的意图",
        signal_context="",
        candidates=_CANDIDATES,
    )
    assert out.template_id == "none"
