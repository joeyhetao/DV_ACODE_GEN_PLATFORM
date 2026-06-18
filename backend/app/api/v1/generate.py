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
    LLMFallbackRequest,
    LLMFallbackResponse,
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
from app.services.core.cache import (
    get_llm_direct_cache,
    set_llm_direct_cache,
)
from app.services.llm.factory import (
    get_default_llm_client,
    get_default_llm_config_id,
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


async def _record_gate_event(
    db: AsyncSession,
    user_id: str,
    original_intent: str,
    gate_error_type: str,
) -> None:
    """L4 analytics 基础设施：5 道闸触发时写一条 GenerationRecord 用于聚合统计。

    template_id / output_code / confidence 都留 None；analytics 端点用
    `gate_error_type IS NOT NULL` 区分闸触发记录。

    先 rollback：pipeline 抛闸异常之前可能往 db.session 里 add 过中间对象
    （intent_cache 之类），那些状态本应随异常被丢弃；不先清洁就直接 add+commit
    会把脏对象一并持久化，破坏 gate 语义。commit 失败再 rollback 一次兜底，
    并 logger.exception 记录，避免把 analytics 写失败吞成沉默 bug。
    """
    try:
        await db.rollback()
        db.add(GenerationRecord(
            user_id=user_id,
            original_intent=original_intent,
            template_id=None,
            output_code=None,
            confidence=None,
            cache_hit=False,
            intent_cache_hit=False,
            generation_mode="rag",
            gate_error_type=gate_error_type,
        ))
        await db.commit()
    except Exception:
        logger.exception("failed to persist gate event for analytics; ignoring")
        await db.rollback()


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
        await _record_gate_event(db, current_user.id, payload.text, "off_topic")
        raise HTTPException(status_code=422, detail=_off_topic_detail(e))
    except CodeTypeMismatchError as e:
        await _record_gate_event(db, current_user.id, payload.text, "code_type_mismatch")
        raise HTTPException(status_code=422, detail=_code_type_mismatch_detail(e))
    except UnderSpecifiedIntentError as e:
        await _record_gate_event(db, current_user.id, payload.text, "under_specified")
        raise HTTPException(status_code=422, detail=_under_specified_detail(e))
    except NoMatchingTemplateError as e:
        await _record_gate_event(db, current_user.id, payload.text, "no_matching_template")
        raise HTTPException(status_code=422, detail=_no_matching_template_detail(e))
    except EmptyRetrievalError as e:
        await _record_gate_event(db, current_user.id, payload.text, "empty_retrieval")
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
        await _record_gate_event(db, current_user.id, payload.text, "off_topic")
        raise HTTPException(status_code=422, detail=_off_topic_detail(e))
    except CodeTypeMismatchError as e:
        await _record_gate_event(db, current_user.id, payload.text, "code_type_mismatch")
        raise HTTPException(status_code=422, detail=_code_type_mismatch_detail(e))
    except UnderSpecifiedIntentError as e:
        await _record_gate_event(db, current_user.id, payload.text, "under_specified")
        raise HTTPException(status_code=422, detail=_under_specified_detail(e))
    except NoMatchingTemplateError as e:
        await _record_gate_event(db, current_user.id, payload.text, "no_matching_template")
        raise HTTPException(status_code=422, detail=_no_matching_template_detail(e))
    except EmptyRetrievalError as e:
        await _record_gate_event(db, current_user.id, payload.text, "empty_retrieval")
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
    record_id: str | None = None
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
            generation_mode="rag",
        )
        db.add(record)
        await db.commit()
        record_id = record.id

    # FEAT-11 Stage 2：/render 始终走 RAG 路径，恒返 generation_mode="rag"。
    # 前端用此字段决定是否显示"对生成结果不满意？尝试 LLM 直接生成"按钮。
    return RenderResponse(
        code=code,
        cache_hit=cache_hit,
        generation_record_id=record_id,
        generation_mode="rag",
    )


@router.post("/llm-fallback", response_model=LLMFallbackResponse)
async def llm_fallback(
    payload: LLMFallbackRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """FEAT-11 Stage 2：用户对 RAG 渲染结果不满意 → 让 LLM 直接生成。

    入参：源 GenerationRecord.id。逻辑：
    1. 加载源记录；不存在 → 404
    2. 源 generation_mode=='llm_direct' → 422（禁止 llm_direct → llm_direct 链）
    3. 构造 cache key（gen_llm:* 7d TTL）；命中 → 返缓存代码（新建 child record 仍写 DB
       但 cache_hit=True）
    4. miss → 调 llm.generate_code_freeform；ValueError("no_sv_code_block") → 422
       detail.type='llm_direct_no_code'
    5. 写新 GenerationRecord(generation_mode='llm_direct', parent_record_id=source.id,
       template_id=None) + 写缓存

    返回 {code, generation_record_id, generation_mode: "llm_direct", cache_hit}
    """
    source = await db.get(GenerationRecord, payload.generation_record_id)
    if source is None:
        raise HTTPException(status_code=404, detail="源生成记录不存在")
    # Stage 2 显式拒链：参见 spec §3 Out — 用户连续点 fallback 应回到原 RAG 重试，
    # 而不是让 llm_direct → llm_direct 累积出"漂得越来越远"的代码。
    if (source.generation_mode or "rag") == "llm_direct":
        raise HTTPException(
            status_code=422,
            detail={
                "type": "llm_direct_chained_not_allowed",
                "message": "源记录已是 LLM 直接生成结果，不支持继续 fallback。",
            },
        )

    # 源记录里没有 clk/rst/signals 单独的列——它们走 params_used 字典还原。
    # params_used 在 RAG 路径下含 {clk, rst, ...}（见 _map_params_with_source step-4
    # default 分支）；若缺，用 PipelineInput 的默认值兜底。
    params_used = source.params_used or {}
    clk = str(params_used.get("clk") or "clk")
    rst = str(params_used.get("rst") or params_used.get("rst_n") or "rst_n")
    # signals 不在 GenerationRecord 落盘——但 freeform 不强依赖结构化信号列表，
    # prompt 会从 intent 文本里直接取。这里传空表，让 build_freeform_prompt 走
    # "未提供信号列表"分支。
    signals: list[dict] = []
    # code_type 唯一可信来源：source.template_id → templates.code_type。
    # 历史上曾尝试用 params_used.__code_type 字典 key 兜底，但 RenderRequest.params 的
    # 写入路径根本不会注入这个 key（review M2 指出），那条路径永远 dead，故移除。
    # 若 source.template_id 缺失或反查不到模板（理论上 RAG 路径不应发生），落回
    # "assertion" 作为表单默认；记录 warning 让后期 admin 知道有兜底命中。
    code_type = ""
    if source.template_id:
        tmpl = await db.get(Template, source.template_id)
        if tmpl and tmpl.code_type:
            code_type = tmpl.code_type
    if not code_type:
        logger.warning(
            "llm_fallback: code_type fallback to 'assertion' for source=%s "
            "(template_id=%s) — coverage requests may be miscategorized",
            source.id, source.template_id,
        )
        code_type = "assertion"

    llm = await get_default_llm_client(db)
    llm_config_id = getattr(llm, "config_id", "") or await get_default_llm_config_id(db)

    cached_code = await get_llm_direct_cache(
        source.original_intent, code_type, signals, clk, rst, llm_config_id
    )
    cache_hit = cached_code is not None
    if cached_code is not None:
        code = cached_code
    else:
        try:
            code = await llm.generate_code_freeform(
                intent=source.original_intent,
                code_type=code_type,
                signals=signals,
                clk=clk,
                rst=rst,
            )
        except ValueError as e:
            if str(e) == "no_sv_code_block":
                raise HTTPException(
                    status_code=422,
                    detail={
                        "type": "llm_direct_no_code",
                        "message": "LLM 未输出可识别的 SystemVerilog 代码块，请稍后重试或换 LLM 配置。",
                    },
                )
            # 兜底：未知 ValueError——logger 留全文，不把 str(e) / type(e).__name__
            # 暴露给客户端（信息泄漏，review M1）。前端只看 generic 提示。
            logger.exception(
                "generate_code_freeform unexpected ValueError: user=%s source=%s",
                current_user.id, source.id,
            )
            raise HTTPException(
                status_code=422,
                detail={
                    "type": "llm_direct_internal_error",
                    "message": "LLM 直接生成内部异常，请稍后重试或联系管理员。",
                },
            )
        except Exception:
            logger.exception(
                "generate_code_freeform unexpected failure: user=%s source=%s",
                current_user.id, source.id,
            )
            raise HTTPException(
                status_code=500,
                detail={
                    "type": "llm_direct_internal_error",
                    "message": "LLM 直接生成内部异常，请稍后重试或联系管理员。",
                },
            )
        await set_llm_direct_cache(
            source.original_intent, code_type, signals, clk, rst, code, llm_config_id
        )

    record = GenerationRecord(
        user_id=current_user.id,
        original_intent=source.original_intent,
        normalized_intent=source.normalized_intent,
        intent_hash=source.intent_hash,
        rag_top3=None,
        template_id=None,
        template_version=None,
        params_used=None,
        output_code=code,
        confidence=None,
        cache_hit=cache_hit,
        intent_cache_hit=False,
        generation_mode="llm_direct",
        parent_record_id=source.id,
    )
    db.add(record)
    await db.commit()

    return LLMFallbackResponse(
        code=code,
        generation_record_id=record.id,
        cache_hit=cache_hit,
    )


@router.get("/code-types")
async def list_code_types(current_user: User = Depends(get_current_user)):
    registry = get_registry()
    return [
        {"id": ct.id, "display_name": ct.display_name}
        for ct in registry.all()
    ]
