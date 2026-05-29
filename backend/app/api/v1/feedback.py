"""L3 用户反馈端点：POST /feedback/{generation_record_id}

权限：JWT 认证；普通用户只能给自己的 generation_record 评分；lib_admin /
super_admin 可给任何人的 record 补评（兜底审核场景）。

写入列：feedback_rating / feedback_reason_tags / feedback_comment /
feedback_at（4 列）+ generation_mode（仅在原 record 没值时回填 'rag'）。
返 204 No Content。
"""
from __future__ import annotations
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.generation_record import GenerationRecord
from app.models.user import User
from app.schemas.feedback import FeedbackCreate

router = APIRouter(prefix="/feedback", tags=["feedback"])

_ADMIN_ROLES = {"lib_admin", "super_admin"}


@router.post("/{generation_record_id}", status_code=204)
async def submit_feedback(
    generation_record_id: str,
    payload: FeedbackCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    record = await db.get(GenerationRecord, generation_record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="generation_record 不存在")

    if record.user_id != current_user.id and current_user.role not in _ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="无权对他人的生成记录评分")

    record.feedback_rating = payload.rating
    record.feedback_reason_tags = (
        [t.value for t in payload.reason_tags] if payload.reason_tags else None
    )
    record.feedback_comment = payload.comment
    record.feedback_at = datetime.now(timezone.utc)
    if not record.generation_mode:
        record.generation_mode = "rag"

    await db.commit()
    return Response(status_code=204)
