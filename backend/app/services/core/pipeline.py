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


async def run_pipeline(inp: PipelineInput, db: AsyncSession) -> PipelineResult:
    # Step 1: Intent Normalize
    normalized, intent_hash = await normalize_intent(inp.original_intent, db)

    # Step 2: Cache Lookup (intent-level)
    history = await lookup_history(intent_hash)
    if history:
        tmpl_id = history.get("template_id")
        tmpl_version = history.get("version", "1")
        params = history.get("param_mapping", {})
        cached_code = await get_generation_cache(tmpl_id, tmpl_version, params)
        if cached_code:
            from app.models.template import Template
            tmpl = await db.get(Template, tmpl_id)
            return PipelineResult(
                status="success",
                code=cached_code,
                template_id=tmpl_id,
                template_name=tmpl.name if tmpl else "",
                version=tmpl.version if tmpl else tmpl_version,
                confidence=history.get("confidence", 1.0),
                normalized_intent=normalized,
                intent_hash=intent_hash,
                rag_candidates=[],
                params_used=params,
                cache_hit=True,
                intent_cache_hit=True,
            )

    # Step 3 + 4: Embed + RAG Retrieve (Stage1 → Stage2 → Stage3)
    rag_candidates = await rag_retrieve(normalized, db, code_type=inp.code_type)
    if not rag_candidates:
        raise ValueError("未能从模板库中检索到合适的模板，请检查意图描述或丰富模板库")

    # 去重：Qdrant 里可能有同一模板的多个 point
    seen_ids: set[str] = set()
    deduped: list[dict] = []
    for c in rag_candidates:
        if c["template_id"] not in seen_ids:
            seen_ids.add(c["template_id"])
            deduped.append(c)
    rag_candidates = deduped

    # 关键词补充召回：弥补向量搜索召回不足（如 FSM → cov_transition_coverage_v1）
    supplements = await _keyword_supplement(
        normalized + " " + inp.original_intent,
        db,
        inp.code_type,
        existing_ids={c["template_id"] for c in rag_candidates},
    )
    if supplements:
        print(f"[Pipeline] keyword supplement: {[s['template_id'] for s in supplements]}", flush=True)
        rag_candidates = supplements + rag_candidates  # 关键词匹配的排在前面

    # Step 5: Template Select via LLM tool call
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

    from app.models.template import Template
    template = None
    if selection.template_id and selection.template_id.lower() not in ("none", "", "null"):
        template = await db.get(Template, selection.template_id)

    # 降级：LLM 选不到时用候选第一名（关键词补充后第一名是最佳匹配）
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

    if not template:
        raise ValueError("未能确定有效模板，请检查模板库或调整意图描述")

    # Step 6: Param Map（意图提取 + LLM映射 + role-hint + 兜底）
    extracted = _extract_params_from_intent(inp.original_intent)
    # LLM 结果优先覆盖提取结果
    merged_mapping = {**extracted, **selection.param_mapping}
    params = _map_params(template, inp, merged_mapping)
    print(f"[Pipeline] params={params}", flush=True)

    # Step 1b: Generation cache lookup (template+params level)
    version_str = str(template.version)
    cached_code = await get_generation_cache(template.id, version_str, params)
    if cached_code:
        rag_summary = [{"template_id": c["template_id"], "name": c["name"], "score": c["score"]} for c in rag_candidates]
        return PipelineResult(
            status="success",
            code=cached_code,
            template_id=template.id,
            template_name=template.name,
            version=version_str,
            confidence=selection.confidence,
            normalized_intent=normalized,
            intent_hash=intent_hash,
            rag_candidates=rag_summary,
            params_used=params,
            cache_hit=True,
            intent_cache_hit=False,
        )

    # Step 7: Render with Jinja2 StrictUndefined
    code = render_template(template.template_body, params, template.id, version_str)

    rag_summary = [{"template_id": c["template_id"], "name": c["name"], "score": c["score"]} for c in rag_candidates]

    # Step 8: Cache Write
    await set_generation_cache(template.id, version_str, params, code)
    await save_history(
        intent_hash=intent_hash,
        template_id=template.id,
        param_mapping=params,
        confidence=selection.confidence,
        code=code,
    )

    return PipelineResult(
        status="success",
        code=code,
        template_id=template.id,
        template_name=template.name,
        version=version_str,
        confidence=selection.confidence,
        normalized_intent=normalized,
        intent_hash=intent_hash,
        rag_candidates=rag_summary,
        params_used=params,
        cache_hit=False,
        intent_cache_hit=False,
    )


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


def _map_params(template, inp: PipelineInput, llm_mapping: dict) -> dict:
    params: dict = {}
    parameters: list[dict] = template.parameters or []

    # Start from merged mapping (extracted + LLM)
    params.update(llm_mapping)

    # Role-hint engine: fill signal roles from inp.signals
    signals_by_role: dict[str, list[dict]] = {}
    for sig in inp.signals:
        role = sig.get("role", "other")
        signals_by_role.setdefault(role, []).append(sig)

    for param_def in parameters:
        name = param_def.get("name")
        if not name or name in params:
            continue
        role_hint = param_def.get("role_hint")
        if role_hint and role_hint in signals_by_role:
            matched = signals_by_role[role_hint]
            params[name] = matched[0]["name"] if len(matched) == 1 else [m["name"] for m in matched]

    # Mandatory defaults from PipelineInput
    for param_def in parameters:
        name = param_def.get("name")
        if not name or name in params:
            continue
        if name == "clk":
            params[name] = inp.clk
        elif name in ("rst", "rst_n"):
            params[name] = inp.rst
        elif name == "rst_polarity":
            params[name] = inp.rst_polarity
        elif "default" in param_def:
            params[name] = param_def["default"]

    # Semantic fallbacks
    for param_def in parameters:
        name = param_def.get("name")
        if not name or name in params:
            continue
        if name == "group_name":
            for sig_key in ("signal", "valid", "data", "state"):
                if sig_key in params:
                    params[name] = params[sig_key]
                    break
            else:
                params[name] = "cov_group"
        elif name == "signal":
            if inp.signals:
                params[name] = inp.signals[0]["name"]
        elif name == "state_list":
            params[name] = "IDLE, ACTIVE, DONE"
        elif name == "bins_expr":
            width = int(params.get("signal_width", 4))
            params[name] = f"{{[0:{2**width - 1}]}}"

    # 最终兜底：required 参数仍缺失时用参数名本身，保证 Jinja2 不崩溃
    for param_def in parameters:
        name = param_def.get("name")
        if name and name not in params and param_def.get("required"):
            params[name] = name

    return params
