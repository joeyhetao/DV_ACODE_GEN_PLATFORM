from __future__ import annotations
import json
import openai

from app.schemas.intent import TemplateSelectionOutput
from app.services.llm.base import LLMClient

_TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "select_template",
        "description": "选择最匹配的模板并填入参数",
        "parameters": {
            "type": "object",
            "properties": {
                "template_id": {"type": "string"},
                "param_mapping": {"type": "object", "additionalProperties": {"type": "string"}},
                "confidence": {"type": "number"},
            },
            "required": ["template_id", "param_mapping", "confidence"],
        },
    },
}


class OpenAICompatLLMClient(LLMClient):
    def __init__(
        self,
        api_key: str,
        model_id: str,
        base_url: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 512,
        output_mode: str = "tool_calling",
    ) -> None:
        self._client = openai.AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._model = model_id
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._output_mode = output_mode

    async def normalize_intent(self, original_intent: str, rules: str) -> str:
        system = f"你是IC验证领域专家。将用户提供的验证意图改写为标准句式。\n\n规则：\n{rules}"
        resp = await self._client.chat.completions.create(
            model=self._model,
            max_tokens=128,
            temperature=self._temperature,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": original_intent},
            ],
        )
        return resp.choices[0].message.content.strip()

    async def select_template(
        self,
        normalized_intent: str,
        signal_context: str,
        candidates: list[dict],
    ) -> TemplateSelectionOutput:
        candidates_text = "\n\n".join(
            f"模板{i + 1}：{c['template_id']} - {c['name']}\n  描述：{c['description']}"
            for i, c in enumerate(candidates)
        )
        system = "你是资深IC验证工程师。从候选模板中选择最匹配的，并将信号角色与参数对应。"
        user = (
            f"{signal_context}\n\n[验证意图]\n{normalized_intent}\n\n"
            f"[候选模板]\n{candidates_text}"
        )

        if self._output_mode == "tool_calling":
            resp = await self._client.chat.completions.create(
                model=self._model,
                max_tokens=self._max_tokens,
                temperature=self._temperature,
                tools=[_TOOL_DEF],
                tool_choice={"type": "function", "function": {"name": "select_template"}},
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
            call = resp.choices[0].message.tool_calls[0]
            inp = json.loads(call.function.arguments)
        else:
            # json_mode fallback
            resp = await self._client.chat.completions.create(
                model=self._model,
                max_tokens=self._max_tokens,
                temperature=self._temperature,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system + "\n输出JSON: {template_id, param_mapping, confidence}"},
                    {"role": "user", "content": user},
                ],
            )
            inp = json.loads(resp.choices[0].message.content)

        return TemplateSelectionOutput(
            template_id=inp["template_id"],
            param_mapping=inp["param_mapping"],
            confidence=float(inp["confidence"]),
        )

    async def test_basic(self) -> str:
        resp = await self._client.chat.completions.create(
            model=self._model,
            max_tokens=64,
            messages=[{"role": "user", "content": "Reply with: OK"}],
        )
        return resp.choices[0].message.content.strip()
