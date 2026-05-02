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
    PreviewResponse,
    ParamWithSource,
    RAGCandidateWithParams,
)
from app.services.core.pipeline import (
    PipelineInput,
    RenderInput,
    run_pipeline,
    pipeline_preview,
    pipeline_render,
)
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
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")

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


@router.post("/preview", response_model=PreviewResponse)
async def preview(
    payload: GenerateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """方案 3 两步式：第一步 — 返回模板推荐 + 参数预填充（含 5 类来源标识）。

    前端拿到后展示确认面板让用户编辑参数，再调 /render 完成渲染。
    意图缓存命中时返回 quick_render=True 让前端跳过确认面板直接调 /render。
    """
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
        result = await pipeline_preview(inp, db)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")

    return PreviewResponse(
        template_id=result.template_id,
        template_name=result.template_name,
        template_version=result.template_version,
        confidence=result.confidence,
        confidence_source=result.confidence_source,
        rag_candidates=[
            RAGCandidateWithParams(
                template_id=c["template_id"],
                name=c["name"],
                score=c["score"],
                parameters=c.get("parameters", []),
            )
            for c in result.rag_candidates
        ],
        params={
            name: ParamWithSource(**meta) for name, meta in result.params.items()
        },
        intent_hash=result.intent_hash,
        normalized_intent=result.normalized_intent,
        quick_render=result.quick_render,
    )


@router.post("/render", response_model=RenderResponse)
async def render(
    payload: RenderRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """方案 3 两步式：第二步 — 用户确认参数后渲染 + 写缓存 + 写 GenerationRecord。

    可由两种调用方进入：
    1. 前端两步式：传完整 intent_hash/confidence/normalized_intent/rag_candidates，
       本端点写完整 GenerationRecord
    2. legacy 重渲染：仅传 template_id/template_version/params，仅渲染不写 record
       （由调用方自决；通过 intent_hash 是否传入区分）
    """
    try:
        render_input = RenderInput(
            template_id=payload.template_id,
            template_version=payload.template_version,
            params=payload.params,
            intent_hash=payload.intent_hash,
            confidence=payload.confidence,
            normalized_intent=payload.normalized_intent,
        )
        code, cache_hit = await pipeline_render(render_input, db)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")

    # 仅在两步式路径（含 intent_hash）下写 GenerationRecord
    if payload.intent_hash:
        record = GenerationRecord(
            user_id=current_user.id,
            original_intent=payload.original_intent or payload.normalized_intent,
            normalized_intent=payload.normalized_intent,
            intent_hash=payload.intent_hash,
            rag_top3=payload.rag_candidates[:3],
            template_id=payload.template_id,
            template_version=payload.template_version,
            params_used=payload.params,
            output_code=code,
            confidence=payload.confidence,
            cache_hit=cache_hit,
            intent_cache_hit=(payload.confidence_source == "intent_cache"),
        )
        db.add(record)
        await db.commit()

    return RenderResponse(code=code, cache_hit=cache_hit)


@router.get("/code-types")
async def list_code_types(current_user: User = Depends(get_current_user)):
    registry = get_registry()
    return [
        {"id": ct.id, "display_name": ct.display_name}
        for ct in registry.all()
    ]
