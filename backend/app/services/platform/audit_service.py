from __future__ import annotations
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.audit_log import AdminAuditLog


async def log_action(
    db: AsyncSession,
    operator_id: str,
    action: str,
    target_type: str,
    target_id: str | None = None,
    detail: dict | None = None,
) -> None:
    log = AdminAuditLog(
        operator_id=operator_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        detail=detail,
    )
    db.add(log)
    await db.flush()
