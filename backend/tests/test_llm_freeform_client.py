"""FEAT-11 Stage 2: LLM freeform 兜底 client 单测.

测 build_freeform_prompt / extract_sv_code_block 两个共享辅助 + 两个 LLM 客户端的
generate_code_freeform 实现（mock SDK，不打真实 LLM）。

跑法：
    docker compose exec backend pytest tests/test_llm_freeform_client.py -v
"""
from __future__ import annotations
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.llm.base import (
    build_freeform_prompt,
    extract_sv_code_block,
)


# ── extract_sv_code_block：纯函数，覆盖 lang 别名 + 拒绝条件 ─────────────

def test_extract_systemverilog_fenced_block():
    text = (
        "Here is the code:\n"
        "```systemverilog\n"
        "module foo; endmodule\n"
        "```"
    )
    assert extract_sv_code_block(text) == "module foo; endmodule"


def test_extract_sv_alias_fenced_block():
    text = "```sv\nproperty p1; endproperty\n```"
    assert extract_sv_code_block(text) == "property p1; endproperty"


def test_extract_verilog_alias_fenced_block():
    text = "```verilog\nwire [3:0] x;\n```"
    assert extract_sv_code_block(text) == "wire [3:0] x;"


def test_extract_bare_fence_without_lang():
    """模型有时漏写 lang——也兼容裸 ``` 兜底，避免误判 no_sv_code_block。"""
    text = "```\nassert property (@(posedge clk) a |-> b);\n```"
    assert extract_sv_code_block(text) == "assert property (@(posedge clk) a |-> b);"


def test_extract_first_block_wins_when_multiple():
    """多个围栏：取第一个；prose 之间的额外块忽略（spec §5：单个 fenced block）。"""
    text = (
        "```systemverilog\nfirst_block\n```\n"
        "Some explanation\n"
        "```systemverilog\nsecond_block\n```"
    )
    assert extract_sv_code_block(text) == "first_block"


def test_extract_raises_on_prose_only():
    """模型回答纯说明文，无围栏 → ValueError('no_sv_code_block') 让端点 422。"""
    text = "I cannot generate SystemVerilog for this request."
    with pytest.raises(ValueError) as excinfo:
        extract_sv_code_block(text)
    assert "no_sv_code_block" in str(excinfo.value)


def test_extract_raises_on_empty_fence():
    text = "```systemverilog\n   \n```"
    with pytest.raises(ValueError) as excinfo:
        extract_sv_code_block(text)
    assert "no_sv_code_block" in str(excinfo.value)


def test_extract_raises_on_empty_string():
    with pytest.raises(ValueError):
        extract_sv_code_block("")


def test_extract_case_insensitive_lang_tag():
    """LLM 大写 SystemVerilog 一样兜得住。"""
    text = "```SystemVerilog\nfoo\n```"
    assert extract_sv_code_block(text) == "foo"


# ── build_freeform_prompt：检查关键约束都进了 prompt ────────────────────

def test_build_freeform_prompt_includes_all_constraints():
    system, user = build_freeform_prompt(
        intent="检查 valid/ready 握手稳定性",
        code_type="assertion",
        signals=[{"name": "valid", "width": 1, "role": "valid"}],
        clk="aclk",
        rst="aresetn",
    )
    # 系统提示包含硬约束（单 fenced + 无 prose + 严格用户信号名）
    assert "systemverilog" in system.lower()
    assert "代码块" in system or "围栏" in system
    # 用户消息携带所有上下文
    assert "assertion" in user
    assert "aclk" in user
    assert "aresetn" in user
    assert "valid" in user
    assert "检查 valid/ready 握手稳定性" in user


def test_build_freeform_prompt_handles_empty_signals():
    """signals=None 也不报错——用户没填信号列表的常见路径。"""
    system, user = build_freeform_prompt(
        intent="reset behavior assertion",
        code_type="assertion",
        signals=None,
        clk="clk",
        rst="rst_n",
    )
    assert "未提供信号列表" in user


# ── OpenAICompatLLMClient.generate_code_freeform：mock SDK ──────────────

@pytest.mark.asyncio
async def test_openai_compat_generate_code_freeform_returns_code():
    """SDK 返带围栏的 SV 代码 → client 抽出 body。"""
    from app.services.llm.openai_compat_client import OpenAICompatLLMClient

    fake_choice = MagicMock()
    fake_choice.message.content = "```systemverilog\nassert property (a |-> b);\n```"
    fake_resp = MagicMock()
    fake_resp.choices = [fake_choice]
    fake_resp.usage = None  # _reasoning_tokens 返 'n/a'

    client = OpenAICompatLLMClient(
        api_key="dummy", model_id="glm-4.7", base_url="http://localhost"
    )
    client._client.chat.completions.create = AsyncMock(return_value=fake_resp)

    code = await client.generate_code_freeform(
        intent="x", code_type="assertion", signals=[], clk="clk", rst="rst_n"
    )
    assert code == "assert property (a |-> b);"
    # 验证 thinking=disabled 硬编码进 extra_body
    create_kwargs = client._client.chat.completions.create.await_args.kwargs
    assert create_kwargs["extra_body"] == {"thinking": {"type": "disabled"}}
    assert create_kwargs["temperature"] == 0.0


@pytest.mark.asyncio
async def test_openai_compat_generate_code_freeform_raises_on_prose():
    """SDK 返 prose-only → 抛 ValueError('no_sv_code_block') 让端点 422。"""
    from app.services.llm.openai_compat_client import OpenAICompatLLMClient

    fake_choice = MagicMock()
    fake_choice.message.content = "I cannot generate SystemVerilog for this."
    fake_resp = MagicMock()
    fake_resp.choices = [fake_choice]
    fake_resp.usage = None

    client = OpenAICompatLLMClient(
        api_key="dummy", model_id="glm-4.7", base_url="http://localhost"
    )
    client._client.chat.completions.create = AsyncMock(return_value=fake_resp)

    with pytest.raises(ValueError) as excinfo:
        await client.generate_code_freeform(
            intent="x", code_type="assertion", signals=[], clk="clk", rst="rst_n"
        )
    assert "no_sv_code_block" in str(excinfo.value)


# ── AnthropicLLMClient.generate_code_freeform：mock SDK ────────────────

@pytest.mark.asyncio
async def test_anthropic_generate_code_freeform_returns_code():
    from app.services.llm.anthropic_client import AnthropicLLMClient

    fake_block = MagicMock()
    fake_block.type = "text"
    fake_block.text = "```systemverilog\ncovergroup cg; endgroup\n```"
    fake_msg = MagicMock()
    fake_msg.content = [fake_block]
    fake_msg.usage = None  # _anthropic_thinking_tokens 兜 'n/a'

    client = AnthropicLLMClient(api_key="dummy", model_id="claude-x")
    client._client.messages.create = AsyncMock(return_value=fake_msg)

    code = await client.generate_code_freeform(
        intent="cover cur_state",
        code_type="coverage",
        signals=[{"name": "cur_state", "width": 3, "role": "state"}],
        clk="clk",
        rst="rst_n",
    )
    assert code == "covergroup cg; endgroup"


@pytest.mark.asyncio
async def test_anthropic_generate_code_freeform_raises_on_prose():
    from app.services.llm.anthropic_client import AnthropicLLMClient

    fake_block = MagicMock()
    fake_block.type = "text"
    fake_block.text = "Sorry, I cannot."
    fake_msg = MagicMock()
    fake_msg.content = [fake_block]
    fake_msg.usage = None

    client = AnthropicLLMClient(api_key="dummy", model_id="claude-x")
    client._client.messages.create = AsyncMock(return_value=fake_msg)

    with pytest.raises(ValueError) as excinfo:
        await client.generate_code_freeform(
            intent="x", code_type="assertion", signals=[], clk="clk", rst="rst_n"
        )
    assert "no_sv_code_block" in str(excinfo.value)
