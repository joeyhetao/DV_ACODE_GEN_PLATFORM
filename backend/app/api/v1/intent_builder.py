"""v3.0 IntentBuilder API: RAG-grounded 多轮对话端点。

- POST /chat：单轮对话，session_id 由前端生成（uuid4），首轮可传空让后端 mint
- GET /scenarios + POST /build：v2 老端点，v3.0 标 deprecated，返 410 Gone

PRD §3.8 重写。
"""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.intent import (
    IntentBuilderChatRequest,
    IntentBuilderChatResponse,
    RAGCandidateBrief,
)
from app.services.intent.conversation import run_one_turn
from app.services.intent.session import (
    IntentBuilderSession,
    load_session,
    mint_session_id,
    save_session,
)
from app.services.llm.factory import get_default_llm_client

router = APIRouter(prefix="/intent-builder", tags=["intent-builder"])


@router.post("/chat", response_model=IntentBuilderChatResponse)
async def chat(
    payload: IntentBuilderChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """v3.0 多轮对话单轮 endpoint。

    流程：
    1. 加载/创建 session（按 user_id 隔离，TTL 24h）
    2. run_one_turn 跑 RAG + LLM 一次
    3. 持久化 session
    4. 返回 assistant_message / accumulated_intent / rag_candidates / suggest_contribute

    无显式"结束会话"端点——24h TTL 自然过期；前端"用这条意图回去生成"或"贡献"按钮
    都只是 router.push 离开本页，session 在 Redis 里继续躺到 TTL 过期。
    """
    # 1. session 加载或创建
    session = await load_session(current_user.id, payload.session_id)
    if session is None:
        # 新会话：mint id（即便前端传了 id 但找不到，也当新会话；防止过期 id 续会）
        new_id = payload.session_id or mint_session_id()
        session = IntentBuilderSession(
            session_id=new_id,
            user_id=current_user.id,
            code_type=payload.code_type,
        )

    # 安全检查：会话锁定 code_type，不允许中途切换（避免上下文混乱）
    if session.code_type != payload.code_type:
        raise HTTPException(
            status_code=400,
            detail=f"会话已锁定 code_type={session.code_type}，本轮传入 {payload.code_type} 不一致；请开新会话",
        )

    # 2. 跑一轮对话
    llm = await get_default_llm_client(db)
    try:
        result = await run_one_turn(
            session=session,
            user_message=payload.user_message,
            db=db,
            llm=llm,
        )
    except Exception as e:
        # LLM / RAG 异常→ 不持久化本轮，原状态返回，让前端重试
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"对话引擎异常：{type(e).__name__}: {e}")

    # 3. 持久化
    await save_session(session)

    # 4. 响应
    return IntentBuilderChatResponse(
        session_id=session.session_id,
        assistant_message=result.assistant_message,
        accumulated_intent=result.accumulated_intent,
        rag_candidates=[
            RAGCandidateBrief(**c) for c in result.rag_candidates
        ],
        suggest_contribute=result.suggest_contribute,
        turn_count=result.turn_count,
    )


# ── v2 老端点保留但返 410 Gone ─────────────────────────────────────────

@router.get("/scenarios")
async def list_scenarios_deprecated(
    code_type: str = "assertion",
    current_user: User = Depends(get_current_user),
):
    """v2 硬编码场景列表，v3.0 由 /chat 多轮对话取代。"""
    raise HTTPException(
        status_code=410,
        detail={
            "type": "endpoint_deprecated",
            "message": "GET /intent-builder/scenarios 已退役，请改用 POST /intent-builder/chat 多轮对话",
            "deprecated_since": "v3.0",
        },
    )


@router.post("/build")
async def build_deprecated(current_user: User = Depends(get_current_user)):
    """v2 表单式 intent builder，v3.0 由 /chat 多轮对话取代。"""
    raise HTTPException(
        status_code=410,
        detail={
            "type": "endpoint_deprecated",
            "message": "POST /intent-builder/build 已退役，请改用 POST /intent-builder/chat 多轮对话",
            "deprecated_since": "v3.0",
        },
    )
