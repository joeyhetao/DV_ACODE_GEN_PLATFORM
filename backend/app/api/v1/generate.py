from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.generation_record import GenerationRecord
from app.models.template import Template
from app.schemas.generate import (
    GenerateRequest,
    GenerateResponse,
    RAGCandidate,
    RenderRequest,
    RenderResponse,
)
from app.services.core.pipeline import PipelineInput, run_pipeline
from app.services.core.renderer import render_template
from app.services.registry import get_registry

router = APIRouter(prefix="/generate", tags=["generate"])


@router.post("", response_model=GenerateResponse)
async def generate(
    payload: GenerateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    registry = get_registry()
    if payload.code_type not in [ct.id for ct in registry.all()]:
        raise HTTPException(status_code=400, detail=f"未知的代码类型: {payload.code_type}")

    inp = PipelineInput(
        original_intent=payload.text,
        code_type=payload.code_type,
        protocol=payload.protocol,
        clk=payload.clk,
        rst=payload.rst,
        rst_polarity=payload.rst_polarity,
        signals=[s.model_dump() for s in payload.signals],
    )

    try:
        result = await run_pipeline(inp, db)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    record = GenerationRecord(
        user_id=current_user.id,
        original_intent=payload.text,
        normalized_intent=result.normalized_intent,
        intent_hash=result.intent_hash,
        rag_top3=result.rag_candidates[:3],
        template_id=result.template_id,
        template_version=result.version,
        params_used=result.params_used,
        output_code=result.code,
        confidence=result.confidence,
        cache_hit=result.cache_hit,
        intent_cache_hit=result.intent_cache_hit,
    )
    db.add(record)
    await db.commit()

    return GenerateResponse(
        status=result.status,
        confidence=result.confidence,
        template_id=result.template_id,
        template_version=result.version,
        cache_hit=result.cache_hit,
        intent_cache_hit=result.intent_cache_hit,
        rag_candidates=[RAGCandidate(**c) for c in result.rag_candidates],
        params_used=result.params_used,
        code=result.code,
    )


@router.post("/render", response_model=RenderResponse)
async def render(
    payload: RenderRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    template = await db.get(Template, payload.template_id)
    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")
    try:
        code = render_template(
            template.template_body,
            payload.params,
            template.id,
            payload.template_version,
        )
    except (ValueError, Exception) as e:
        raise HTTPException(status_code=422, detail=str(e))
    return RenderResponse(code=code)


@router.get("/code-types")
async def list_code_types(current_user: User = Depends(get_current_user)):
    registry = get_registry()
    return [
        {"id": ct.id, "display_name": ct.display_name}
        for ct in registry.all()
    ]
