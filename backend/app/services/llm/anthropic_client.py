from __future__ import annotations
import json
import time
import anthropic
import httpx

from app.schemas.intent import TemplateSelectionOutput
from app.services.llm.base import (
    LLMClient,
    build_freeform_prompt,
    extract_sv_code_block,
)


def _anthropic_thinking_tokens(msg) -> str:
    """Anthropic extended thinking 暴露在 usage 上的字段名按 SDK 版本变动；
    取不到就返 n/a，与 OpenAI-compat 的 [Timing] 日志格式对齐。"""
    usage = getattr(msg, "usage", None)
    if not usage:
        return "n/a"
    for attr in ("thinking_tokens", "reasoning_tokens"):
        val = getattr(usage, attr, None)
        if val is not None:
            return str(val)
    return "n/a"


# thinking 模型（GLM-4.7、DeepSeek-R1、Claude 4.x extended thinking 等）单次推理 20-60s。
# 显式设 read=300s，避免默认 connect=5s 在网络抖动时早断；read=300s 跟 nginx 同步。
_LLM_HTTPX_TIMEOUT = httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=10.0)

_TOOL_DEF = {
    "name": "select_template",
    "description": "选择最匹配的模板并填入参数",
    "input_schema": {
        "type": "object",
        "properties": {
            "template_id": {"type": "string", "description": "选择的模板ID"},
            "param_mapping": {
                "type": "object",
                "description": "参数名到信号名/值的映射",
                "additionalProperties": {"type": "string"},
            },
            "confidence": {
                "type": "number",
                "description": "匹配置信度 0.0-1.0",
            },
        },
        "required": ["template_id", "param_mapping", "confidence"],
    },
}


class AnthropicLLMClient(LLMClient):
    def __init__(self, api_key: str, model_id: str, temperature: float = 0.0, max_tokens: int = 512) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key, timeout=_LLM_HTTPX_TIMEOUT)
        self._model = model_id
        self._temperature = temperature
        self._max_tokens = max_tokens

    async def normalize_intent(self, original_intent: str, rules: str) -> str:
        system = f"你是IC验证领域专家。将用户提供的验证意图改写为标准句式。\n\n规则：\n{rules}"
        _t = time.perf_counter()
        msg = await self._client.messages.create(
            model=self._model,
            max_tokens=128,
            temperature=self._temperature,
            system=system,
            messages=[{"role": "user", "content": original_intent}],
        )
        print(
            f"[Timing] llm=normalize_intent ms={int((time.perf_counter() - _t) * 1000)} "
            f"reasoning_tokens={_anthropic_thinking_tokens(msg)} thinking=n/a",
            flush=True,
        )
        return msg.content[0].text.strip()

    async def select_template(
        self,
        normalized_intent: str,
        signal_context: str,
        candidates: list[dict],
        original_intent: str = "",
    ) -> TemplateSelectionOutput:
        candidates_text = "\n\n".join(
            f"模板{i + 1}：{c['template_id']} - {c['name']}\n"
            f"  描述：{c['description']}\n"
            f"  参数：{self._format_params(c.get('template'))}"
            for i, c in enumerate(candidates)
        )

        system = (
            "你是资深IC验证工程师。从候选模板中选择最匹配的，并将信号角色与参数对应。\n"
            "严格使用工具调用输出，不要输出任何其他内容。\n"
            "负向规则：若没有任何候选模板的验证语义与用户意图匹配，在 template_id 字段填入字符串 none，"
            "param_mapping 填空对象，confidence 填 0.0；"
            "禁止通过信号角色重命名来强行适配语义不符的模板。"
        )
        # original_intent 保留用户原始信号名/状态枚举（normalize 可能改写），优先填参数；
        # 与 OpenAICompatLLMClient._step2_fill_params 行为对齐。
        raw_intent_block = (
            f"\n\n[用户原始描述]\n{original_intent}" if original_intent else ""
        )
        user = (
            f"{signal_context}\n\n[验证意图]\n{normalized_intent}{raw_intent_block}\n\n"
            f"[候选模板]\n{candidates_text}"
        )

        _t = time.perf_counter()
        msg = await self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            temperature=self._temperature,
            system=system,
            tools=[_TOOL_DEF],
            tool_choice={"type": "tool", "name": "select_template"},
            messages=[{"role": "user", "content": user}],
        )
        print(
            f"[Timing] llm=select_template ms={int((time.perf_counter() - _t) * 1000)} "
            f"reasoning_tokens={_anthropic_thinking_tokens(msg)} thinking=n/a",
            flush=True,
        )

        for block in msg.content:
            if block.type == "tool_use" and block.name == "select_template":
                inp = block.input
                return TemplateSelectionOutput(
                    template_id=inp["template_id"],
                    param_mapping=inp["param_mapping"],
                    confidence=float(inp["confidence"]),
                )

        raise RuntimeError("LLM 未调用 select_template 工具")

    async def chat(
        self,
        messages: list[dict],
        max_tokens: int = 1024,
        temperature: float | None = None,
    ) -> str:
        """v3.0 通用多轮接口。Anthropic SDK 把 system 单独成参数，需要从 messages 拆出。

        IntentBuilder + 贡献 LLM 反推 parameters 用。Anthropic 默认不开 extended_thinking
        （需要额外参数显式开），所以默认行为已经满足 IntentBuilder"低延迟稳定多轮"需求。
        """
        # 提取 system message（若存在），其余传给 messages.create
        system_content = ""
        chat_messages = []
        for m in messages:
            if m.get("role") == "system":
                system_content = m.get("content", "")
            else:
                chat_messages.append(m)
        _t = time.perf_counter()
        msg = await self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            temperature=temperature if temperature is not None else self._temperature,
            system=system_content,
            messages=chat_messages,
        )
        print(
            f"[Timing] llm=chat ms={int((time.perf_counter() - _t) * 1000)} "
            f"reasoning_tokens={_anthropic_thinking_tokens(msg)} thinking=n/a "
            f"messages_count={len(messages)}",
            flush=True,
        )
        # Anthropic content 是 list[ContentBlock]，取第一个 text block
        for block in msg.content:
            if getattr(block, "type", None) == "text":
                return block.text.strip()
        return ""

    async def generate_code_freeform(
        self,
        intent: str,
        code_type: str,
        signals: list[dict],
        clk: str,
        rst: str,
    ) -> str:
        """FEAT-11 Stage 2 兜底：LLM 直接生成代码，绕过 RAG + Jinja2。

        Anthropic 原生 messages.create，无 thinking 参数（默认即 off）。max_tokens 给 4096——
        即便 GLM-4.7 大模板也极少超 800 tokens；Claude 大模型可能用更多 system 输出。
        """
        system, user = build_freeform_prompt(intent, code_type, signals, clk, rst)
        _t = time.perf_counter()
        msg = await self._client.messages.create(
            model=self._model,
            max_tokens=4096,
            temperature=0.0,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        print(
            f"[Timing] llm=generate_code_freeform ms={int((time.perf_counter() - _t) * 1000)} "
            f"reasoning_tokens={_anthropic_thinking_tokens(msg)} thinking=n/a",
            flush=True,
        )
        text = ""
        for block in msg.content:
            if getattr(block, "type", None) == "text":
                text = block.text
                break
        return extract_sv_code_block(text)

    async def test_basic(self) -> str:
        msg = await self._client.messages.create(
            model=self._model,
            max_tokens=64,
            messages=[{"role": "user", "content": "Reply with: OK"}],
        )
        return msg.content[0].text.strip()

    @staticmethod
    def _format_params(template) -> str:
        if not template or not hasattr(template, "parameters"):
            return ""
        params = template.parameters or []
        return ", ".join(
            f"{p['name']}({p.get('type', 'signal')})"
            for p in params
        )
