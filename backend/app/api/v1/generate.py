from __future__ import annotations
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

logger = logging.getLogger(__name__)

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
    OffTopicIntentError,
    EmptyRetrievalError,
    CodeTypeMismatchError,
    UnderSpecifiedIntentError,
    NoMatchingTemplateError,
    PipelineInput,
    RenderInput,
    run_pipeline,
    pipeline_preview,
    pipeline_render,
)


def _off_topic_detail(e: OffTopicIntentError) -> dict:
    # v3.0：off-topic 不带 redirect_to——IntentBuilder 救不了真离题，让用户停留生成页改提问
    return {
        "type": "off_topic",
        "message": "输入似乎与 IC 验证需求无关。请描述要验证的信号、协议或具体属性。",
        "detector": e.detector,
        "top_dense_score": round(e.top_dense_score, 4),
        "threshold": e.threshold,
        "redirect_to": None,
    }


def _empty_retrieval_detail(e: EmptyRetrievalError) -> dict:
    # v3.0：基础设施异常不带 redirect_to——前端只能弹"请稍后或联系管理员"
    return {
        "type": "empty_retrieval",
        "message": "模板库检索返空——疑似 Qdrant 或检索服务异常。请稍后重试或联系管理员。",
        "code_type": e.code_type,
        "redirect_to": None,
    }


def _code_type_mismatch_detail(e: CodeTypeMismatchError) -> dict:
    # v3.0：code_type 错配不带 redirect_to——前端在原页面弹 Modal 引导切换 code_type
    return {
        "type": "code_type_mismatch",
        "message": (
            f"意图语义看起来更像「{e.suggested_code_type}」类型，"
            f"但你选的是「{e.selected_code_type}」。请先切换 code_type 再生成。"
        ),
        "detector": e.detector,
        "selected_code_type": e.selected_code_type,
        "suggested_code_type": e.suggested_code_type,
        "selected_score": round(e.selected_score, 4),
        "suggested_score": round(e.suggested_score, 4),
        "redirect_to": None,
    }


def _no_matching_template_detail(e: NoMatchingTemplateError) -> dict:
    # 第五道闸：库内无此场景模板，redirect_to 直接跳贡献页（携带 description + code_type）
    intent_preview = e.original_intent[:40] + ("…" if len(e.original_intent) > 40 else "")
    return {
        "type": "no_matching_template",
        "message": (
            f"库内暂无与「{intent_preview}」匹配的模板（最近候选相似度 {e.top_score:.2f}）。"
            "欢迎贡献该验证场景，丰富模板库。"
        ),
        "detector": e.detector,
        "top_score": round(e.top_score, 4),
        "redirect_to": e.redirect_to,
    }


def _under_specified_detail(e: UnderSpecifiedIntentError) -> dict:
    # v3.0：under_specified 带 redirect_to=/intent-builder?...——前端 handleApiError
    # 读到后无脑 router.push，让用户进 IntentBuilder 多轮对话补足参数信息
    names = "、".join(
        f"「{p['name']}」（{p['description']}）" if p.get("description") else f"「{p['name']}」"
        for p in e.missing_params
    )
    return {
        "type": "under_specified",
        "message": (
            f"已识别模板「{e.template_name}」（{e.template_id}），但你的描述里"
            f"没说清楚以下必填参数：{names}。请补充后重试。"
        ),
        "detector": e.detector,
        "template_id": e.template_id,
        "template_name": e.template_name,
        "missing_params": e.missing_params,
        "redirect_to": e.redirect_to,
    }
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
        source=payload.source,
    )

    try:
        result = await run_pipeline(inp, db)
    except OffTopicIntentError as e:
        raise HTTPException(status_code=422, detail=_off_topic_detail(e))
    except CodeTypeMismatchError as e:
        raise HTTPException(status_code=422, detail=_code_type_mismatch_detail(e))
    except UnderSpecifiedIntentError as e:
        raise HTTPException(status_code=422, detail=_under_specified_detail(e))
    except NoMatchingTemplateError as e:
        raise HTTPException(status_code=422, detail=_no_matching_template_detail(e))
    except EmptyRetrievalError as e:
        raise HTTPException(status_code=503, detail=_empty_retrieval_detail(e))
    except ValueError as e:
        logger.warning(
            "run_pipeline ValueError: user=%s code_type=%s text_len=%s err=%s",
            current_user.id, payload.code_type, len(payload.text or ""), e,
        )
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(
            "run_pipeline unexpected failure: user=%s code_type=%s text_len=%s",
            current_user.id, payload.code_type, len(payload.text or ""),
        )
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
        source=payload.source,
    )

    try:
        result = await pipeline_preview(inp, db)
        # PreviewResponse 构造也包进 try：Pydantic 校验失败时也走结构化 500，
        # 而不是绕开本 except chain 进 FastAPI 默认 handler → 前端看不到 detail.type。
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
    except OffTopicIntentError as e:
        raise HTTPException(status_code=422, detail=_off_topic_detail(e))
    except CodeTypeMismatchError as e:
        raise HTTPException(status_code=422, detail=_code_type_mismatch_detail(e))
    except UnderSpecifiedIntentError as e:
        raise HTTPException(status_code=422, detail=_under_specified_detail(e))
    except NoMatchingTemplateError as e:
        raise HTTPException(status_code=422, detail=_no_matching_template_detail(e))
    except EmptyRetrievalError as e:
        raise HTTPException(status_code=503, detail=_empty_retrieval_detail(e))
    except ValueError as e:
        logger.warning(
            "pipeline_preview ValueError: user=%s code_type=%s text_len=%s err=%s",
            current_user.id, payload.code_type, len(payload.text or ""), e,
        )
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(
            "pipeline_preview unexpected failure: user=%s code_type=%s text_len=%s",
            current_user.id, payload.code_type, len(payload.text or ""),
        )
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")


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
        logger.warning(
            "pipeline_render ValueError: user=%s template=%s err=%s",
            current_user.id, payload.template_id, e,
        )
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(
            "pipeline_render unexpected failure: user=%s template=%s",
            current_user.id, payload.template_id,
        )
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
