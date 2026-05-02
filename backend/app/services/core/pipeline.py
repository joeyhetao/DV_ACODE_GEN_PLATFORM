from __future__ import annotations
import re
import json
from dataclasses import dataclass, field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.services.core.cache import (
    get_generation_cache,
    set_generation_cache,
    get_intent_cache,
    set_intent_cache,
)
from app.services.core.renderer import render_template
from app.services.intent.normalizer import normalize_intent
from app.services.intent.history import lookup_history, save_history
from app.services.rag.engine import rag_retrieve
from app.services.llm.factory import get_default_llm_client


@dataclass
class PipelineInput:
    original_intent: str
    code_type: str
    protocol: str | None = None
    clk: str = "clk"
    rst: str = "rst_n"
    rst_polarity: str = "低有效"
    signals: list[dict] = field(default_factory=list)


@dataclass
class PipelineResult:
    """legacy 一步式返回（run_pipeline / batch_tasks 用）。"""
    status: str
    code: str
    template_id: str
    template_name: str
    version: str
    confidence: float
    normalized_intent: str
    intent_hash: str
    rag_candidates: list[dict]
    params_used: dict
    cache_hit: bool = False
    intent_cache_hit: bool = False


@dataclass
class PreviewResult:
    """方案 3 两步式：第一步 preview 输出（含参数来源标识）。"""
    template_id: str
    template_name: str
    template_version: str
    confidence: float
    confidence_source: str                       # "llm_step1" | "rag_fallback" | "intent_cache"
    rag_candidates: list[dict]                   # 含 parameters 字段供前端切换用
    params: dict[str, dict]                      # {name: {value, source, required, description, type}}
    intent_hash: str
    normalized_intent: str
    quick_render: bool = False                   # intent_cache 命中 → True，前端跳确认面板


@dataclass
class RenderInput:
    """方案 3 两步式：第二步 render 输入（用户确认/编辑后的最终参数）。"""
    template_id: str
    template_version: str
    params: dict                                 # value-only dict
    intent_hash: str | None = None               # 透传以关联 history
    confidence: float = 0.0
    normalized_intent: str = ""


async def pipeline_preview(inp: PipelineInput, db: AsyncSession) -> PreviewResult:
    """两步式流水线第一步：意图归一化 → RAG → LLM 选模板/填参数 → 参数源标注。

    不渲染、不写代码缓存。意图缓存命中时返回 quick_render=True 让前端直接调 render。
    """
    from app.models.template import Template

    # Step 1: Intent Normalize
    normalized, intent_hash = await normalize_intent(inp.original_intent, db)

    # Step 2: Intent Cache Lookup
    history = await lookup_history(intent_hash)
    if history:
        tmpl_id = history.get("template_id")
        tmpl_version = history.get("version", "1")
        history_params = history.get("param_mapping", {})
        cached_code = await get_generation_cache(tmpl_id, tmpl_version, history_params)
        if cached_code:
            tmpl = await db.get(Template, tmpl_id)
            # 缓存命中：构建一个最小 PreviewResult，标记 quick_render
            params_with_source = {
                name: {"value": v, "source": "default", "required": True, "description": "", "type": "string"}
                for name, v in history_params.items()
            }
            return PreviewResult(
                template_id=tmpl_id,
                template_name=tmpl.name if tmpl else "",
                template_version=tmpl.version if tmpl else tmpl_version,
                confidence=history.get("confidence", 1.0),
                confidence_source="intent_cache",
                rag_candidates=[],
                params=params_with_source,
                intent_hash=intent_hash,
                normalized_intent=normalized,
                quick_render=True,
            )

    # Step 3 + 4: RAG Retrieve
    rag_candidates = await rag_retrieve(normalized, db, code_type=inp.code_type)
    if not rag_candidates:
        raise ValueError("未能从模板库中检索到合适的模板，请检查意图描述或丰富模板库")

    seen_ids: set[str] = set()
    deduped: list[dict] = []
    for c in rag_candidates:
        if c["template_id"] not in seen_ids:
            seen_ids.add(c["template_id"])
            deduped.append(c)
    rag_candidates = deduped

    # Step 4b: Keyword Supplement
    supplements = await _keyword_supplement(
        normalized + " " + inp.original_intent,
        db,
        inp.code_type,
        existing_ids={c["template_id"] for c in rag_candidates},
    )
    if supplements:
        print(f"[Pipeline] keyword supplement: {[s['template_id'] for s in supplements]}", flush=True)
        rag_candidates = supplements + rag_candidates

    # Step 5: LLM Step1 + Step2
    llm = await get_default_llm_client(db)
    signal_context = _build_signal_context(inp)
    candidate_dicts = [
        {
            "template_id": c["template_id"],
            "name": c["name"],
            "description": c["description"],
            "score": c["score"],
            "parameters": c["template"].parameters if c.get("template") else [],
        }
        for c in rag_candidates
    ]
    selection = await llm.select_template(
        normalized, signal_context, candidate_dicts, original_intent=inp.original_intent
    )
    print(f"[Pipeline] LLM selection: template_id={selection.template_id!r} confidence={selection.confidence}", flush=True)

    template = None
    confidence_source = "llm_step1"
    if selection.template_id and selection.template_id.lower() not in ("none", "", "null"):
        template = await db.get(Template, selection.template_id)

    # Fallback: LLM 选不到时取 RAG 第一名
    if not template:
        fallback_id = rag_candidates[0]["template_id"]
        template = await db.get(Template, fallback_id)
        print(f"[Pipeline] LLM selected '{selection.template_id}', fallback to: {fallback_id}", flush=True)
        if template:
            from app.schemas.intent import TemplateSelectionOutput
            selection = TemplateSelectionOutput(
                template_id=fallback_id,
                param_mapping=selection.param_mapping,
                confidence=float(rag_candidates[0]["score"]),
            )
            confidence_source = "rag_fallback"

    if not template:
        raise ValueError("未能确定有效模板，请检查模板库或调整意图描述")

    # Step 6: Param Map with source tracking
    regex_mapping = _extract_params_from_intent(inp.original_intent)
    params_with_source = _map_params_with_source(
        template, inp, regex_mapping=regex_mapping, llm_mapping=selection.param_mapping
    )
    print(f"[Pipeline] params={_values_only(params_with_source)}", flush=True)

    # 构建 RAG 候选摘要（含 parameters 供前端切换用）
    rag_summary = [
        {
            "template_id": c["template_id"],
            "name": c["name"],
            "score": c["score"],
            "parameters": c["template"].parameters if c.get("template") else [],
        }
        for c in rag_candidates
    ]

    return PreviewResult(
        template_id=template.id,
        template_name=template.name,
        template_version=str(template.version),
        confidence=selection.confidence,
        confidence_source=confidence_source,
        rag_candidates=rag_summary,
        params=params_with_source,
        intent_hash=intent_hash,
        normalized_intent=normalized,
        quick_render=False,
    )


async def pipeline_render(req: RenderInput, db: AsyncSession) -> tuple[str, bool]:
    """两步式流水线第二步：用户确认参数后渲染 + 写缓存 + 保存历史。

    返回 (code, cache_hit)。GenerationRecord 由 API 端点写（不在此函数内）。
    """
    from app.models.template import Template
    template = await db.get(Template, req.template_id)
    if not template:
        raise ValueError(f"模板不存在: {req.template_id}")

    # Step 5b: Generation cache lookup
    version_str = str(template.version)
    cached_code = await get_generation_cache(template.id, version_str, req.params)
    if cached_code:
        return cached_code, True

    # Step 7: Render
    code = render_template(template.template_body, req.params, template.id, version_str)

    # Step 8: Cache write + history save
    await set_generation_cache(template.id, version_str, req.params, code)
    if req.intent_hash:
        await save_history(
            intent_hash=req.intent_hash,
            template_id=template.id,
            param_mapping=req.params,
            confidence=req.confidence,
            code=code,
        )

    return code, False


async def run_pipeline(inp: PipelineInput, db: AsyncSession) -> PipelineResult:
    """legacy 一步式封装：依次调 preview + render，给 batch_tasks / 既有 /generate 端点用。"""
    preview = await pipeline_preview(inp, db)
    params_value_only = _values_only(preview.params)

    if preview.quick_render:
        # intent_cache 命中：preview 已经把缓存 code 透传了；需要 render 来取 code
        # 但缓存的 code 在 history 里，需要重查 generation_cache
        cached_code = await get_generation_cache(
            preview.template_id, preview.template_version, params_value_only
        )
        if cached_code:
            return PipelineResult(
                status="success",
                code=cached_code,
                template_id=preview.template_id,
                template_name=preview.template_name,
                version=preview.template_version,
                confidence=preview.confidence,
                normalized_intent=preview.normalized_intent,
                intent_hash=preview.intent_hash,
                rag_candidates=[],
                params_used=params_value_only,
                cache_hit=True,
                intent_cache_hit=True,
            )

    render_input = RenderInput(
        template_id=preview.template_id,
        template_version=preview.template_version,
        params=params_value_only,
        intent_hash=preview.intent_hash,
        confidence=preview.confidence,
        normalized_intent=preview.normalized_intent,
    )
    code, cache_hit = await pipeline_render(render_input, db)

    rag_summary = [
        {"template_id": c["template_id"], "name": c["name"], "score": c["score"]}
        for c in preview.rag_candidates
    ]
    return PipelineResult(
        status="success",
        code=code,
        template_id=preview.template_id,
        template_name=preview.template_name,
        version=preview.template_version,
        confidence=preview.confidence,
        normalized_intent=preview.normalized_intent,
        intent_hash=preview.intent_hash,
        rag_candidates=rag_summary,
        params_used=params_value_only,
        cache_hit=cache_hit,
        intent_cache_hit=False,
    )


def _values_only(params_with_source: dict[str, dict]) -> dict:
    """从 {name: {value, source, ...}} 提取纯值字典，供 render_template 使用。"""
    return {name: meta["value"] for name, meta in params_with_source.items()}


async def _keyword_supplement(
    intent: str,
    db: AsyncSession,
    code_type: str,
    existing_ids: set[str],
    top_n: int = 2,
) -> list[dict]:
    """直接查 DB 补充关键词匹配的模板，弥补向量搜索的召回盲区。"""
    from app.models.template import Template
    stmt = select(Template).where(Template.code_type == code_type, Template.is_active == True)
    result = await db.execute(stmt)
    all_templates = result.scalars().all()

    intent_lower = intent.lower()
    scored: list[tuple[int, Template]] = []
    for tmpl in all_templates:
        if tmpl.id in existing_ids:
            continue
        keywords = tmpl.keywords or []
        score = sum(1 for kw in keywords if kw.lower() in intent_lower)
        if score > 0:
            scored.append((score, tmpl))

    scored.sort(key=lambda x: -x[0])

    supplements = []
    for score, tmpl in scored[:top_n]:
        supplements.append({
            "template_id": tmpl.id,
            "name": tmpl.name,
            "description": tmpl.description,
            "score": float(score) * 0.1,
            "template": tmpl,
        })
    return supplements


_ASSERTION_SIGNAL_PATTERNS: list[tuple[str, list[str]]] = [
    (r'使能(?:信号)?名?\s*[为是：:]\s*([A-Za-z_]\w*)',           ['enable']),
    (r'数据(?:信号)?名?\s*[为是：:]\s*([A-Za-z_]\w*)',           ['data']),
    (r'valid(?:\s*信号)?\s*[为是：:]\s*([A-Za-z_]\w*)',          ['valid']),
    (r'ready(?:\s*信号)?\s*[为是：:]\s*([A-Za-z_]\w*)',          ['ready']),
    (r'目标(?:信号)?名?\s*[为是：:]\s*([A-Za-z_]\w*)',           ['target']),
    (r'起始(?:信号|事件)?\s*[为是：:]\s*([A-Za-z_]\w*)',         ['start_event']),
    (r'(?:结束|应答)(?:信号|事件)?\s*[为是：:]\s*([A-Za-z_]\w*)', ['end_event']),
    (r'状态信号(?:名)?\s*[为是：:]\s*([A-Za-z_]\w*)',            ['state_sig']),
]


def _extract_params_from_intent(intent: str) -> dict:
    """从自然语言描述中用正则提取常见参数值。

    覆盖范围：
      coverage 模板：signal / group_name / signal_width / state_list / bins_expr
      assertion 模板：module_name / max_cycles / max_delay / init_value /
                     enable / data / valid / ready / target / start_event /
                     end_event / state_sig（强分隔符模式，要求"X 信号 [名] [为/是/:] Y"）

    不覆盖（依赖 LLM Step2 + signal-list role-hint 兜底）：
      from_state / to_state / condition（fsm_state_transition）— 太语义化
      settle_cycles（reset_behavior）— 与 max_cycles 单位冲突
    """
    params: dict = {}

    # ── coverage 模板参数 ──────────────────────────────────────────────────

    # 信号名：状态信号名为cur_state / 信号名为xxx / 信号xxx
    m = re.search(r'(?:状态)?信号名?[为是：:]\s*(\w+)', intent)
    if m:
        params["signal"] = m.group(1)
        params["group_name"] = m.group(1)

    # 位宽：位宽3位 / 3位宽 / 位宽为3
    m = re.search(r'位宽[为是]?\s*(\d+)|(\d+)\s*位(?:宽)?', intent)
    if m:
        params["signal_width"] = int(m.group(1) or m.group(2))

    # 状态列表：优先从"状态包括/有/为"等关键词后提取，避免误匹配 FSM 等缩写
    # 由于 Python 3 \w 包含 CJK 字符，\b 在 "括IDLE" 这种位置不会触发，需要用上下文锚点
    state_section = re.search(r'(?:状态)?(?:包括|有|为|是|包含)\s*([A-Z][A-Z0-9_、,，\s]+)', intent)
    if state_section:
        states = re.findall(r'[A-Z][A-Z0-9_]+', state_section.group(1))
    else:
        # 兜底：取所有 ≥3 字符的大写序列（过滤掉 FSM 等 2-3 字缩写需另判）
        states = re.findall(r'(?<![A-Za-z])[A-Z][A-Z0-9_]{2,}(?![A-Za-z])', intent)
    if len(states) >= 2:
        params["state_list"] = ", ".join(states)
        params["bins_expr"] = "{" + ", ".join(states) + "}"

    # ── assertion 模板参数 ────────────────────────────────────────────────

    # module_name：模块名为 reg_block / 模块名是 X / 模块: X
    m = re.search(r'模块名?\s*[为是：:]\s*([A-Za-z_]\w*)', intent)
    if m:
        params["module_name"] = m.group(1)

    # max_cycles / max_delay：N 周期内 / N 个周期 / 8 周期
    # 同时填两个 key，模板 parameters 里没声明的会被 _map_params 静默忽略
    m = re.search(r'(\d+)\s*(?:个)?\s*周期(?:内|以内)?', intent)
    if m:
        n = int(m.group(1))
        params["max_cycles"] = n
        params["max_delay"] = n

    # init_value：初始值为 0 / 复位值: 0xFF / 初始值是 1
    # 注意：hex 模式必须排在 \d+ 之前，否则 \d+ 会先匹配 "0xFF" 中的 "0" 就停下
    m = re.search(r'(?:初始|复位)值\s*[为是：:]?\s*(0[xX][\da-fA-F]+|\d+)', intent)
    if m:
        params["init_value"] = m.group(1)

    # 信号名（保守模式，要求强分隔符 [为是：:]）
    for pattern, param_names in _ASSERTION_SIGNAL_PATTERNS:
        m = re.search(pattern, intent, re.IGNORECASE)
        if m:
            for pname in param_names:
                params.setdefault(pname, m.group(1))

    print(f"[Pipeline] extracted from intent: {params}", flush=True)
    return params


def _build_signal_context(inp: PipelineInput) -> str:
    lines = [f"时钟: {inp.clk}", f"复位: {inp.rst}（{inp.rst_polarity}）"]
    if inp.protocol:
        lines.append(f"协议: {inp.protocol}")
    if inp.signals:
        lines.append("信号列表:")
        for s in inp.signals:
            lines.append(f"  - {s['name']} [width={s.get('width', 1)}] role={s.get('role', 'other')}")
    return "\n".join(lines)


def _map_params_with_source(
    template,
    inp: PipelineInput,
    regex_mapping: dict,
    llm_mapping: dict,
) -> dict[str, dict]:
    """方案 3：返回每参数的 value + source 标识（5 类源），供前端 5 色徽标显示。

    优先级（与 legacy _map_params 对齐：LLM > regex > signal-list > default > placeholder）：
      1. llm        — LLM Step2 推断
      2. regex      — _extract_params_from_intent 正则提取
      3. signal_list — 用户填写的信号列表 + role-hint 自动映射
      4. default    — 模板 default 字段 / clk/rst/rst_polarity from PipelineInput / 语义兜底
      5. placeholder — required 参数仍缺失时用参数名本身（生成代码会出现字面量，必须用户改）
    """
    parameters: list[dict] = template.parameters or []
    param_meta = {p["name"]: p for p in parameters if p.get("name")}
    result: dict[str, dict] = {}

    def _set(name: str, value, source: str) -> None:
        if name in result:
            return
        meta = param_meta.get(name, {})
        result[name] = {
            "value": value,
            "source": source,
            "required": meta.get("required", False),
            "description": meta.get("description", ""),
            "type": meta.get("type", "string"),
        }

    # 1. LLM 优先（与 legacy {**extracted, **selection.param_mapping} 保持一致）
    for name, value in llm_mapping.items():
        _set(name, value, "llm")

    # 2. regex（不覆盖 LLM）
    for name, value in regex_mapping.items():
        _set(name, value, "regex")

    # 3. signal-list role-hint
    signals_by_role: dict[str, list[dict]] = {}
    for sig in inp.signals:
        role = sig.get("role", "other")
        signals_by_role.setdefault(role, []).append(sig)

    for param_def in parameters:
        name = param_def.get("name")
        if not name or name in result:
            continue
        role_hint = param_def.get("role_hint")
        if role_hint and role_hint in signals_by_role:
            matched = signals_by_role[role_hint]
            value = matched[0]["name"] if len(matched) == 1 else [m["name"] for m in matched]
            _set(name, value, "signal_list")

    # 4. defaults（clk/rst/rst_polarity from PipelineInput + template default）
    for param_def in parameters:
        name = param_def.get("name")
        if not name or name in result:
            continue
        if name == "clk":
            _set(name, inp.clk, "default")
        elif name in ("rst", "rst_n"):
            _set(name, inp.rst, "default")
        elif name == "rst_polarity":
            _set(name, inp.rst_polarity, "default")
        elif "default" in param_def:
            _set(name, param_def["default"], "default")

    # 5. semantic fallbacks
    for param_def in parameters:
        name = param_def.get("name")
        if not name or name in result:
            continue
        if name == "group_name":
            value = "cov_group"
            for sig_key in ("signal", "valid", "data", "state"):
                if sig_key in result:
                    value = result[sig_key]["value"]
                    break
            _set(name, value, "default")
        elif name == "signal":
            if inp.signals:
                _set(name, inp.signals[0]["name"], "default")
        elif name == "state_list":
            _set(name, "IDLE, ACTIVE, DONE", "default")
        elif name == "bins_expr":
            width = 4
            if "signal_width" in result:
                try:
                    width = int(result["signal_width"]["value"])
                except (TypeError, ValueError):
                    pass
            _set(name, f"{{[0:{2**width - 1}]}}", "default")

    # 6. placeholder（required 参数兜底用参数名本身）
    for param_def in parameters:
        name = param_def.get("name")
        if name and name not in result and param_def.get("required"):
            _set(name, name, "placeholder")

    return result
