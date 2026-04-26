from __future__ import annotations
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
        # Try generation cache with previously used template+params
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
    selection = await llm.select_template(normalized, signal_context, candidate_dicts)

    from app.models.template import Template
    template = await db.get(Template, selection.template_id)
    if not template:
        raise ValueError(f"LLM 选择的模板 {selection.template_id} 不存在")

    # Step 6: Param Map (role-hint engine + LLM mapping)
    params = _map_params(template, inp, selection.param_mapping)

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

    # Start from LLM-provided mapping
    params.update(llm_mapping)

    # Apply role-hint engine: fill signal roles from inp.signals
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
            if len(matched) == 1:
                params[name] = matched[0]["name"]
            else:
                params[name] = [m["name"] for m in matched]

    # Fill mandatory defaults from PipelineInput
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

    return params
