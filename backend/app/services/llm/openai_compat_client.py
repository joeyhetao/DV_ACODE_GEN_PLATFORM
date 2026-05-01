from __future__ import annotations
import json
import re
import openai

from app.schemas.intent import TemplateSelectionOutput
from app.services.llm.base import LLMClient


def _extract_json(text: str) -> dict:
    """从 LLM 文本响应中提取第一个 JSON 对象，兼容 markdown 代码块。"""
    block = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if block:
        return json.loads(block.group(1))
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if not match:
        raise ValueError(f"LLM 响应中未找到 JSON: {text[:300]}")
    return json.loads(match.group())


class OpenAICompatLLMClient(LLMClient):
    def __init__(
        self,
        api_key: str,
        model_id: str,
        base_url: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 2048,
        output_mode: str = "tool_calling",
    ) -> None:
        self._client = openai.AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._model = model_id
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._output_mode = output_mode  # 保留字段供未来扩展，当前两步均使用纯文本

    async def normalize_intent(self, original_intent: str, rules: str) -> str:
        system = f"你是IC验证领域专家。将用户提供的验证意图改写为标准句式。\n\n规则：\n{rules}"
        # 同 Step1/Step2，GLM-4.7 thinking 模型需要更大 max_tokens 缓冲 reasoning。
        resp = await self._client.chat.completions.create(
            model=self._model,
            max_tokens=4096,
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
        original_intent: str = "",
    ) -> TemplateSelectionOutput:
        """两步调用：第一步选模板ID，第二步填参数。职责分离，避免单次输出过长。"""

        # ── Step 1：选模板 ID（max_tokens=64，输出极短）────────────────────────
        template_id = await self._step1_select_id(normalized_intent, candidates)
        print(f"[GLM Step1] selected={template_id!r}", flush=True)

        # ── Step 2：填参数（max_tokens=512，仅针对已选模板）──────────────────
        selected = next((c for c in candidates if c["template_id"] == template_id), None)
        param_mapping: dict = {}
        if selected:
            parameters = selected.get("parameters", [])
            required_params = [p for p in parameters if p.get("required")]
            if required_params:
                # 优先用 original_intent（含原始信号名/状态列表），无则用 normalized
                fill_text = original_intent or normalized_intent
                param_mapping = await self._step2_fill_params(
                    fill_text, signal_context, template_id, required_params
                )
                print(f"[GLM Step2] param_mapping={param_mapping}", flush=True)

        confidence = 0.9 if template_id else 0.0
        return TemplateSelectionOutput(
            template_id=template_id or "",
            param_mapping=param_mapping,
            confidence=confidence,
        )

    async def _step1_select_id(self, normalized_intent: str, candidates: list[dict]) -> str:
        """Step 1：纯文本返回一个 template_id，max_tokens=64。"""
        candidates_text = "\n".join(
            f"{i + 1}. {c['template_id']}  {c['name']}  {c['description'][:60]}"
            for i, c in enumerate(candidates)
        )
        print(f"[GLM Step1] candidates:\n{candidates_text}", flush=True)

        system = (
            "你是IC验证工程师。从候选模板中选一个最匹配的，只返回其 template_id 字段值，不要其他任何内容。\n"
            "匹配规则：FSM/状态机/状态转换 → 选含 transition 的；"
            "握手/valid/ready → 选含 handshake 的；值域/bins/枚举 → 选含 value 的；"
            "交叉/cross → 选含 cross 的。"
        )
        user = (
            f"[验证意图]\n{normalized_intent}\n\n"
            f"[候选模板]\n{candidates_text}\n\n"
            f"只返回 template_id："
        )

        # GLM-4.7 是 thinking 模型，会在输出前消耗大量 reasoning_tokens（实测 ~650 tokens）；
        # max_tokens 同时限制 reasoning+output 总和，不足则 finish_reason=length 且 content=''。
        # 给 4096 留足 thinking 缓冲，最终答案 ~10 tokens 可以稳定输出。
        resp = await self._client.chat.completions.create(
            model=self._model,
            max_tokens=4096,
            temperature=0.0,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        content = (resp.choices[0].message.content or "").strip()
        print(f"[GLM Step1] raw={content!r} finish={resp.choices[0].finish_reason}", flush=True)

        # 精确匹配候选 ID
        for c in candidates:
            if c["template_id"] in content:
                return c["template_id"]
        return ""

    async def _step2_fill_params(
        self,
        intent: str,
        signal_context: str,
        template_id: str,
        required_params: list[dict],
    ) -> dict:
        """Step 2：针对已选模板的必填参数，从描述中提取真实值，返回 dict。"""
        params_desc = "\n".join(
            f"- {p['name']}: {p.get('description', '')}（类型: {p.get('type', 'string')}）"
            for p in required_params
        )
        system = (
            "你是IC验证工程师。根据用户描述，为指定模板填写参数的真实值。\n"
            "要求：只返回 JSON 对象，不要其他说明；"
            "参数值必须来自描述中的实际内容，不要使用占位符。"
        )
        user = (
            f"{signal_context}\n\n"
            f"[用户描述]\n{intent}\n\n"
            f"[模板 {template_id} 的必填参数]\n{params_desc}\n\n"
            f'输出示例：{{"group_name": "cur_state", "signal": "cur_state", "signal_width": "3"}}'
        )

        # 同 Step1，GLM-4.7 thinking 消耗大量 tokens；JSON 输出可能 ~50 tokens，但需 4096 缓冲。
        resp = await self._client.chat.completions.create(
            model=self._model,
            max_tokens=4096,
            temperature=0.0,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        content = resp.choices[0].message.content or ""
        print(f"[GLM Step2] raw={content!r} finish={resp.choices[0].finish_reason}", flush=True)

        try:
            return _extract_json(content)
        except Exception:
            return {}

    async def test_basic(self) -> str:
        resp = await self._client.chat.completions.create(
            model=self._model,
            max_tokens=64,
            messages=[{"role": "user", "content": "Reply with: OK"}],
        )
        return resp.choices[0].message.content.strip()
