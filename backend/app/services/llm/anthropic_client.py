from __future__ import annotations
import json
import anthropic

from app.schemas.intent import TemplateSelectionOutput
from app.services.llm.base import LLMClient

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
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model_id
        self._temperature = temperature
        self._max_tokens = max_tokens

    async def normalize_intent(self, original_intent: str, rules: str) -> str:
        system = f"你是IC验证领域专家。将用户提供的验证意图改写为标准句式。\n\n规则：\n{rules}"
        msg = await self._client.messages.create(
            model=self._model,
            max_tokens=128,
            temperature=self._temperature,
            system=system,
            messages=[{"role": "user", "content": original_intent}],
        )
        return msg.content[0].text.strip()

    async def select_template(
        self,
        normalized_intent: str,
        signal_context: str,
        candidates: list[dict],
    ) -> TemplateSelectionOutput:
        candidates_text = "\n\n".join(
            f"模板{i + 1}：{c['template_id']} - {c['name']}\n"
            f"  描述：{c['description']}\n"
            f"  参数：{self._format_params(c.get('template'))}"
            for i, c in enumerate(candidates)
        )

        system = (
            "你是资深IC验证工程师。从候选模板中选择最匹配的，并将信号角色与参数对应。\n"
            "严格使用工具调用输出，不要输出任何其他内容。"
        )
        user = (
            f"{signal_context}\n\n[验证意图]\n{normalized_intent}\n\n"
            f"[候选模板]\n{candidates_text}"
        )

        msg = await self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            temperature=self._temperature,
            system=system,
            tools=[_TOOL_DEF],
            tool_choice={"type": "tool", "name": "select_template"},
            messages=[{"role": "user", "content": user}],
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
