from __future__ import annotations
import json
import re
import time
import httpx
import openai

from app.schemas.intent import TemplateSelectionOutput
from app.services.llm.base import LLMClient


# thinking 模型（GLM-4.7、DeepSeek-R1 等）单次推理 20-60s。显式设 read=300s 避免默认
# 5s connect 在网络抖动时早断；与 nginx proxy_read_timeout=300s 对齐。
_LLM_HTTPX_TIMEOUT = httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=10.0)


def _extract_json(text: str) -> dict:
    """从 LLM 文本响应中提取第一个 JSON 对象，兼容 markdown 代码块。"""
    block = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if block:
        return json.loads(block.group(1))
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if not match:
        raise ValueError(f"LLM 响应中未找到 JSON: {text[:300]}")
    return json.loads(match.group())


def _reasoning_tokens(resp) -> int | str:
    """从 OpenAI 兼容响应里取 reasoning_tokens；非 thinking 模型或 SDK 旧版返 'n/a'。"""
    try:
        details = resp.usage.completion_tokens_details
        if details is None:
            return "n/a"
        if isinstance(details, dict):
            return details.get("reasoning_tokens", "n/a")
        return getattr(details, "reasoning_tokens", "n/a")
    except AttributeError:
        return "n/a"


class OpenAICompatLLMClient(LLMClient):
    def __init__(
        self,
        api_key: str,
        model_id: str,
        base_url: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 2048,
        output_mode: str = "tool_calling",
        step2_disable_thinking: bool = True,
    ) -> None:
        self._client = openai.AsyncOpenAI(
            api_key=api_key, base_url=base_url, timeout=_LLM_HTTPX_TIMEOUT,
        )
        self._model = model_id
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._output_mode = output_mode  # 保留字段供未来扩展，当前两步均使用纯文本
        # step2 是否禁 thinking。normalize/step1 已硬编码禁；step2 默认禁但可通过 Admin UI 关掉。
        self._step2_disable_thinking = step2_disable_thinking

    async def normalize_intent(self, original_intent: str, rules: str) -> str:
        system = f"你是IC验证领域专家。将用户提供的验证意图改写为标准句式。\n\n规则：\n{rules}"
        # 纯句式改写不需要 chain-of-thought：thinking={"type":"disabled"} 跳过 reasoning_tokens，
        # max_tokens 收回到 512（实测输出 ≤ 200 tokens）。非 thinking 模型忽略 extra_body 字段。
        _t = time.perf_counter()
        resp = await self._client.chat.completions.create(
            model=self._model,
            max_tokens=512,
            temperature=self._temperature,
            extra_body={"thinking": {"type": "disabled"}},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": original_intent},
            ],
        )
        print(
            f"[Timing] llm=normalize_intent ms={int((time.perf_counter() - _t) * 1000)} "
            f"reasoning_tokens={_reasoning_tokens(resp)} thinking=off",
            flush=True,
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

        # ── Step 2：填参数（max_tokens=1024，保留 thinking，仅针对已选模板）──────────────────
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
            "交叉/cross → 选含 cross 的。\n"
            "负向规则：若候选模板的核心验证目的与用户意图不符（例如意图是\"互斥约束/one-hot/竞争检测\"，"
            "但候选均为握手/稳定性/延迟/FSM/值域），禁止通过信号名重命名来强行匹配；"
            "此时只返回字符串 none，不要返回任何模板 ID。"
        )
        user = (
            f"[验证意图]\n{normalized_intent}\n\n"
            f"[候选模板]\n{candidates_text}\n\n"
            f"只返回 template_id："
        )

        # Step1 是 pick-from-list 分类，依赖 system prompt 里的 FSM/handshake/value/cross 规则即可，
        # 无需 chain-of-thought：thinking={"type":"disabled"} 跳过 reasoning_tokens，
        # max_tokens=64 容纳 ~10 token 的 template_id 输出。误判由 pipeline.py 的 RAG fallback 兜底。
        _t = time.perf_counter()
        resp = await self._client.chat.completions.create(
            model=self._model,
            max_tokens=64,
            temperature=0.0,
            extra_body={"thinking": {"type": "disabled"}},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        print(
            f"[Timing] llm=step1_select_id ms={int((time.perf_counter() - _t) * 1000)} "
            f"reasoning_tokens={_reasoning_tokens(resp)} thinking=off",
            flush=True,
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

        # Step2 由 self._step2_disable_thinking（来自 llm_configs.step2_disable_thinking）控制：
        # - True（默认）：禁 thinking，max_tokens=2048（纯输出可宽，反正不再被 reasoning 占）。
        #   实测 GLM-4.7 single call ~3s 稳定。
        # - False：保留 thinking，max_tokens=1024（reasoning ≤ 600 + JSON ~150）。FSM state_list /
        #   bins_expr 等边界场景靠推理填准；但实测方差 12-249s，偶发 finish=length 返空。
        if self._step2_disable_thinking:
            create_kwargs: dict = {"extra_body": {"thinking": {"type": "disabled"}}}
            step2_max_tokens = 2048
            thinking_label = "off"
        else:
            create_kwargs = {}
            step2_max_tokens = 1024
            thinking_label = "on"

        _t = time.perf_counter()
        resp = await self._client.chat.completions.create(
            model=self._model,
            max_tokens=step2_max_tokens,
            temperature=0.0,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            **create_kwargs,
        )
        print(
            f"[Timing] llm=step2_fill_params ms={int((time.perf_counter() - _t) * 1000)} "
            f"reasoning_tokens={_reasoning_tokens(resp)} thinking={thinking_label}",
            flush=True,
        )
        content = resp.choices[0].message.content or ""
        print(f"[GLM Step2] raw={content!r} finish={resp.choices[0].finish_reason}", flush=True)

        try:
            return _extract_json(content)
        except Exception:
            return {}

    async def chat(
        self,
        messages: list[dict],
        max_tokens: int = 1024,
        temperature: float | None = None,
    ) -> str:
        """v3.0 通用多轮接口。IntentBuilder + 贡献 LLM 反推 parameters 用。

        默认禁 thinking——多轮对话需要稳定低延迟，不需要 reasoning_tokens。
        若 caller 需要 thinking，自行包装 extra_body 调底层 SDK（本接口不暴露）。
        """
        _t = time.perf_counter()
        resp = await self._client.chat.completions.create(
            model=self._model,
            max_tokens=max_tokens,
            temperature=temperature if temperature is not None else self._temperature,
            extra_body={"thinking": {"type": "disabled"}},
            messages=messages,
        )
        print(
            f"[Timing] llm=chat ms={int((time.perf_counter() - _t) * 1000)} "
            f"reasoning_tokens={_reasoning_tokens(resp)} thinking=off "
            f"messages_count={len(messages)}",
            flush=True,
        )
        return (resp.choices[0].message.content or "").strip()

    async def test_basic(self) -> str:
        resp = await self._client.chat.completions.create(
            model=self._model,
            max_tokens=64,
            messages=[{"role": "user", "content": "Reply with: OK"}],
        )
        return resp.choices[0].message.content.strip()
