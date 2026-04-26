from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.database import get_db
from app.core.security import get_current_user, require_role
from app.models.user import User
from app.models.audit_log import AdminAuditLog
from app.models.generation_record import GenerationRecord
from app.schemas.user import UserOut, UserRoleUpdate
from app.services.platform.backup_service import create_pg_backup
from app.core.config import get_settings

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/users", response_model=list[UserOut])
async def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("super_admin")),
):
    stmt = select(User).order_by(User.created_at.desc())
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.patch("/users/{user_id}/role", response_model=UserOut)
async def update_user_role(
    user_id: str,
    payload: UserRoleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("super_admin")),
):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if payload.role not in ("user", "lib_admin", "super_admin"):
        raise HTTPException(status_code=400, detail="无效的角色")
    user.role = payload.role
    await db.commit()
    await db.refresh(user)
    return user


@router.patch("/users/{user_id}/activate")
async def set_user_active(
    user_id: str,
    active: bool = True,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("super_admin")),
):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    user.is_active = active
    await db.commit()
    return {"user_id": user_id, "is_active": active}


@router.get("/audit-logs")
async def list_audit_logs(
    action: str | None = None,
    operator_id: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("lib_admin", "super_admin")),
):
    stmt = select(AdminAuditLog).order_by(AdminAuditLog.created_at.desc())
    if action:
        stmt = stmt.where(AdminAuditLog.action == action)
    if operator_id:
        stmt = stmt.where(AdminAuditLog.operator_id == operator_id)
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(stmt)
    logs = result.scalars().all()
    return [
        {
            "id": log.id,
            "operator_id": log.operator_id,
            "action": log.action,
            "target_type": log.target_type,
            "target_id": log.target_id,
            "detail": log.detail,
            "created_at": log.created_at,
        }
        for log in logs
    ]


@router.get("/stats")
async def get_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("lib_admin", "super_admin")),
):
    total_users = (await db.execute(select(func.count(User.id)))).scalar()
    total_generations = (await db.execute(select(func.count(GenerationRecord.id)))).scalar()
    cache_hits = (
        await db.execute(
            select(func.count(GenerationRecord.id)).where(GenerationRecord.cache_hit == True)
        )
    ).scalar()
    return {
        "total_users": total_users,
        "total_generations": total_generations,
        "cache_hit_rate": round(cache_hits / total_generations, 4) if total_generations else 0.0,
    }


@router.post("/backup")
async def trigger_backup(
    current_user: User = Depends(require_role("super_admin")),
):
    settings = get_settings()
    out_file = await create_pg_backup(settings.database_url)
    return {"status": "ok", "file": str(out_file)}
