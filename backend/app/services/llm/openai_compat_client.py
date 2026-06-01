from __future__ import annotations
import json
import re
import time
import httpx
import openai

from app.schemas.intent import TemplateSelectionOutput
from app.services.llm.base import (
    LLMClient,
    build_freeform_prompt,
    extract_sv_code_block,
)


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


def _render_step1_candidate(i: int, c: dict) -> str:
    """Step1 候选 Markdown 多行块渲染。

    description 截断 1000（原 60 → A4 扩到 300 → C1 修复后改 1000）：旧值 60 严重
    不足以表达"做什么/典型场景/边界"三要素；lib_manager.py import 时还把
    differentiators / non_use_cases 拼到 description 末尾（"区别要点：..."、
    "不适用场景：..."），合计实测可达 812 char（protocol_handshake_coverage），
    所以截断设到 1000 留余量，避免 non_use_cases 末项被切掉（review NEW-1）。
    顶端用 `###` 标题让 LLM 容易解析"块边界"——若回归发现 LLM 在长候选列表里
    选错块号，可考虑改成 `<candidate id="...">` XML 风格再观察。
    """
    desc = (c.get("description") or "")[:1000]
    return f"### {i + 1}. {c['template_id']}  {c['name']}\n描述：{desc}"


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
        """Step 1：纯文本返回一个 template_id，max_tokens=64（输出仅 ~10 tokens）。

        候选文本以 Markdown 多行块渲染：description 截断 60→300 char；
        若候选携带 differentiators / non_use_cases（template YAML 新字段）则一并展示，
        让 LLM 在近邻混淆对（handshake_stable ↔ handshake_timeout 等）上有足够信息区分。
        max_tokens 保持 64：候选文本扩容仅影响 input tokens（5×300 ≈ 1500），output
        不变；GLM-4.7 在更长 prompt 下 step1 延迟增幅实测 < 1s。
        """
        candidates_text = "\n".join(
            _render_step1_candidate(i, c) for i, c in enumerate(candidates)
        )
        print(f"[GLM Step1] candidates:\n{candidates_text}", flush=True)

        system = (
            "你是IC验证工程师，判断用户意图能否被候选模板覆盖。\n"
            "\n"
            "判断流程：\n"
            "1. 识别意图的核心验证语义（如：握手协议、FSM转换、互斥约束、值域覆盖、延迟约束等）\n"
            "2. 逐一核查候选模板的验证目的是否与该语义一致\n"
            "3. 匹配 → 返回 template_id；无任何候选匹配 → 返回字符串 none\n"
            "\n"
            "候选描述末尾可能附『区别要点』段（列出与最近邻模板的区别要点）和『不适用场景』段"
            "（列出不适用场景），请优先用这两段做区分判断。\n"
            "\n"
            "严格禁止：\n"
            "- 禁止通过重命名信号角色（如把 cpu_req 当 valid/start_event，把 dma_req 当 ready/end_event）强行适配语义不符的模板\n"
            "- '互斥约束/两信号不能同时有效/one-hot/竞争检测/仲裁' 与 '握手协议/稳定性/延迟/超时/复位/FSM/值域覆盖' 是不同语义类别，不可互换\n"
            "- 若候选中无专门处理互斥/one-hot/同时有效约束的模板，必须返回 none\n"
            "\n"
            "只返回 template_id 或 none，不输出其他任何内容。"
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

    async def verify_step1_selection(
        self,
        normalized_intent: str,
        selected_template_id: str,
        candidates: list[dict],
    ) -> bool:
        """A8 二次验证：发一条 yes/no 问题，确认 selected_template 的核心验证语义与意图一致。

        触发位置：pipeline.py step1 之后、A9 reranker gate 之前（confidence_source ==
        "llm_step1" 时）。
        失败开放原则（fail-open）：解析失败 / 异常 / 模型超时一律返 True，避免新加这条
        验证反而成为误拒来源；仅在 LLM 明确回 "no" 时把 confidence_source 降级。

        max_tokens=16：足够 'yes'/'no' + 偶尔的小标点/换行，又不至于让模型展开论证。
        thinking 显式 disabled（与 _step1_select_id 同理：分类任务不需要 CoT）。
        """
        selected = next((c for c in candidates if c["template_id"] == selected_template_id), None)
        if selected is None:
            # 选中的 id 不在候选列表里 —— 不太可能（pipeline 已经做过精确匹配），
            # 但若发生只能 fail-open，让 step1 选择继续走。
            return True

        # description 字段在 lib_manager.import 时已经把 differentiators / non_use_cases
        # 拼到末尾（"区别要点：..."、"不适用场景：..." 段），截断 1000 让所有段都看得到
        # （实测合成最长 812 char，与 _render_step1_candidate 对齐；review NEW-1）。
        desc = (selected.get("description") or "")[:1000]

        system = (
            "你是IC验证工程师。给定用户验证意图和一个已选定的模板，判断该模板的核心验证语义"
            "是否真的与用户意图一致。\n"
            "只回答一个单词：yes 或 no。\n"
            "判断标准：\n"
            "- yes：模板做的事情就是用户要做的事情（不只是关键词重合，而是验证语义一致）\n"
            "- no：模板做的事情与用户意图核心不同（如 timeout 模板被选到 stable 场景，"
            "或 transition 覆盖率被选到 value 覆盖率场景）\n"
            "模板描述末尾可能附『区别要点』和『不适用场景』段，请优先用它们做判断。\n"
            "不要给出解释、不要给出推理过程，只输出 yes 或 no。"
        )
        user = (
            f"[用户意图]\n{normalized_intent}\n"
            f"\n[已选模板]\nid: {selected['template_id']}\n"
            f"名称: {selected.get('name', '')}\n"
            f"描述：{desc}\n"
            f"\n回答（yes 或 no）："
        )

        _t = time.perf_counter()
        try:
            resp = await self._client.chat.completions.create(
                model=self._model,
                max_tokens=16,
                temperature=0.0,
                extra_body={"thinking": {"type": "disabled"}},
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
        except Exception as e:
            print(f"[GLM Step1Verify] LLM call failed → fail-open: {e}", flush=True)
            return True

        print(
            f"[Timing] llm=verify_step1_selection ms={int((time.perf_counter() - _t) * 1000)} "
            f"reasoning_tokens={_reasoning_tokens(resp)} thinking=off",
            flush=True,
        )
        content = (resp.choices[0].message.content or "").strip().lower()
        print(f"[GLM Step1Verify] id={selected_template_id!r} raw={content!r}", flush=True)
        # 解析：以"第一个 token 精确等于 no"为否定信号——单纯 startswith("no") 会把
        # "not sure" / "not applicable" 这类犹豫回答也判成否定，违反 fail-open 原则
        # （review M2）。剥两端常见标点，让 "no." / "no," / "no!" 也算 no。
        tokens = content.split()
        first_clean = (tokens[0].rstrip(",.!?;:") if tokens else "")
        if first_clean == "no":
            return False
        # 其他（'yes' / 'maybe' / 'not sure' / 任何无法解析的回复）一律 fail-open 放过。
        return True

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

    async def generate_code_freeform(
        self,
        intent: str,
        code_type: str,
        signals: list[dict],
        clk: str,
        rst: str,
    ) -> str:
        """FEAT-11 Stage 2 兜底：LLM 直接生成代码，绕过 RAG + Jinja2。

        thinking 硬编码 disabled——freeform 代码生成不需要 reasoning_tokens 占用输出空间，
        且 GLM-4.7 在 thinking on 时常返 finish=length。max_tokens=4096 覆盖典型断言/覆盖率。
        """
        system, user = build_freeform_prompt(intent, code_type, signals, clk, rst)
        _t = time.perf_counter()
        resp = await self._client.chat.completions.create(
            model=self._model,
            max_tokens=4096,
            temperature=0.0,
            extra_body={"thinking": {"type": "disabled"}},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        print(
            f"[Timing] llm=generate_code_freeform ms={int((time.perf_counter() - _t) * 1000)} "
            f"reasoning_tokens={_reasoning_tokens(resp)} thinking=off",
            flush=True,
        )
        content = resp.choices[0].message.content or ""
        return extract_sv_code_block(content)

    async def test_basic(self) -> str:
        resp = await self._client.chat.completions.create(
            model=self._model,
            max_tokens=64,
            messages=[{"role": "user", "content": "Reply with: OK"}],
        )
        return resp.choices[0].message.content.strip()
