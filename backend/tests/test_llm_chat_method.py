"""v3.0 LLMClient.chat() 抽象方法 + 两个 client 实现验证。

主要锁定：
- chat 接口签名稳定（messages: list[dict], max_tokens, temperature）
- OpenAI 兼容 client 把 messages 原样传 SDK
- Anthropic client 自动从 messages 拆 system content（SDK 单独参数）
- 默认禁 thinking（多轮稳定低延迟）
- 返回值是 stripped text

跑法：docker compose exec backend pytest tests/test_llm_chat_method.py -v
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.llm.openai_compat_client import OpenAICompatLLMClient
from app.services.llm.anthropic_client import AnthropicLLMClient


@pytest.mark.asyncio
async def test_openai_compat_chat_passes_messages_to_sdk():
    """OpenAI 兼容 client.chat() 应当原样把 messages 列表传给 SDK。"""
    client = OpenAICompatLLMClient(api_key="x", model_id="glm-4.7", base_url="http://test")
    # mock SDK 的 chat.completions.create
    fake_resp = MagicMock()
    fake_resp.choices = [MagicMock(message=MagicMock(content="  hello world  "))]
    fake_resp.usage = MagicMock()
    fake_resp.usage.completion_tokens_details = MagicMock(reasoning_tokens=0)
    client._client.chat.completions.create = AsyncMock(return_value=fake_resp)

    messages = [
        {"role": "system", "content": "你是一个 IC 验证助手。"},
        {"role": "user", "content": "FSM 是什么"},
    ]
    out = await client.chat(messages, max_tokens=512)

    # 返回值 strip 过
    assert out == "hello world"
    # SDK 被调用一次
    client._client.chat.completions.create.assert_awaited_once()
    call_kwargs = client._client.chat.completions.create.call_args.kwargs
    # messages 原样传
    assert call_kwargs["messages"] == messages
    # max_tokens 透传
    assert call_kwargs["max_tokens"] == 512
    # 默认禁 thinking
    assert call_kwargs.get("extra_body", {}).get("thinking", {}).get("type") == "disabled"


@pytest.mark.asyncio
async def test_openai_compat_chat_temperature_override():
    """temperature 显式传入应覆盖 client 默认。"""
    client = OpenAICompatLLMClient(
        api_key="x", model_id="glm-4.7", base_url="http://test", temperature=0.0,
    )
    fake_resp = MagicMock()
    fake_resp.choices = [MagicMock(message=MagicMock(content="ok"))]
    fake_resp.usage = MagicMock()
    fake_resp.usage.completion_tokens_details = MagicMock(reasoning_tokens=0)
    client._client.chat.completions.create = AsyncMock(return_value=fake_resp)

    await client.chat([{"role": "user", "content": "x"}], temperature=0.7)
    call_kwargs = client._client.chat.completions.create.call_args.kwargs
    assert call_kwargs["temperature"] == 0.7


@pytest.mark.asyncio
async def test_anthropic_chat_extracts_system_from_messages():
    """Anthropic SDK 要 system 作为顶层参数，chat() 必须从 messages 列表拆出 system。"""
    client = AnthropicLLMClient(api_key="x", model_id="claude-sonnet-4-6")
    # mock SDK
    fake_block = MagicMock(type="text", text="  response text  ")
    fake_msg = MagicMock(content=[fake_block])
    fake_msg.usage = MagicMock()
    client._client.messages.create = AsyncMock(return_value=fake_msg)

    messages = [
        {"role": "system", "content": "你是 IC 助手"},
        {"role": "user", "content": "FSM"},
        {"role": "assistant", "content": "我是助手"},
        {"role": "user", "content": "再问一次"},
    ]
    out = await client.chat(messages, max_tokens=512)
    assert out == "response text"

    client._client.messages.create.assert_awaited_once()
    call_kwargs = client._client.messages.create.call_args.kwargs
    # system 被拆出
    assert call_kwargs["system"] == "你是 IC 助手"
    # 剩下的 user/assistant 按顺序进 messages
    assert call_kwargs["messages"] == [
        {"role": "user", "content": "FSM"},
        {"role": "assistant", "content": "我是助手"},
        {"role": "user", "content": "再问一次"},
    ]
    assert call_kwargs["max_tokens"] == 512


@pytest.mark.asyncio
async def test_anthropic_chat_no_system_message():
    """没有 system message 时 system 参数应是空串。"""
    client = AnthropicLLMClient(api_key="x", model_id="claude-sonnet-4-6")
    fake_msg = MagicMock(content=[MagicMock(type="text", text="ok")])
    fake_msg.usage = MagicMock()
    client._client.messages.create = AsyncMock(return_value=fake_msg)

    await client.chat([{"role": "user", "content": "hi"}])
    call_kwargs = client._client.messages.create.call_args.kwargs
    assert call_kwargs["system"] == ""


@pytest.mark.asyncio
async def test_anthropic_chat_non_text_block_returns_empty():
    """SDK 偶尔返非 text block（如 tool_use）时 chat() 不应崩，返空串。"""
    client = AnthropicLLMClient(api_key="x", model_id="claude-sonnet-4-6")
    fake_msg = MagicMock(content=[MagicMock(type="tool_use", text=None)])
    fake_msg.usage = MagicMock()
    client._client.messages.create = AsyncMock(return_value=fake_msg)

    out = await client.chat([{"role": "user", "content": "x"}])
    assert out == ""


# ── P2-20 Anthropic chat 补测 ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_anthropic_chat_first_text_block_is_returned():
    """SDK 返多 block（text + tool_use 等）时 chat() 应取第一个 type='text' 的 block 文本。"""
    client = AnthropicLLMClient(api_key="x", model_id="claude-sonnet-4-6")
    fake_msg = MagicMock(content=[
        MagicMock(type="tool_use", text=None),
        MagicMock(type="text", text="  primary text  "),
        MagicMock(type="text", text="secondary"),
    ])
    fake_msg.usage = MagicMock()
    client._client.messages.create = AsyncMock(return_value=fake_msg)

    out = await client.chat([{"role": "user", "content": "x"}])
    assert out == "primary text"


@pytest.mark.asyncio
async def test_anthropic_chat_temperature_override():
    """显式 temperature 覆盖 client 默认。"""
    client = AnthropicLLMClient(api_key="x", model_id="claude-sonnet-4-6", temperature=0.0)
    fake_msg = MagicMock(content=[MagicMock(type="text", text="ok")])
    fake_msg.usage = MagicMock()
    client._client.messages.create = AsyncMock(return_value=fake_msg)

    await client.chat([{"role": "user", "content": "x"}], temperature=0.5)
    call_kwargs = client._client.messages.create.call_args.kwargs
    assert call_kwargs["temperature"] == 0.5


@pytest.mark.asyncio
async def test_anthropic_chat_max_tokens_propagated():
    """max_tokens 透传给 Anthropic SDK。"""
    client = AnthropicLLMClient(api_key="x", model_id="claude-sonnet-4-6")
    fake_msg = MagicMock(content=[MagicMock(type="text", text="ok")])
    fake_msg.usage = MagicMock()
    client._client.messages.create = AsyncMock(return_value=fake_msg)

    await client.chat([{"role": "user", "content": "x"}], max_tokens=2048)
    call_kwargs = client._client.messages.create.call_args.kwargs
    assert call_kwargs["max_tokens"] == 2048
