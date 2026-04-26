from __future__ import annotations
import uuid
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contribution import TemplateContribution
from app.models.notification import Notification
from app.services.platform.audit_service import log_action


async def approve_contribution(
    contribution: TemplateContribution,
    reviewer_id: str,
    db: AsyncSession,
    template_create_fn,
) -> str:
    promoted_id = await template_create_fn(
        name=contribution.template_name,
        code_type=contribution.code_type,
        description=contribution.description,
        template_body=contribution.demo_code,
        keywords=contribution.keywords or [],
        subcategory=contribution.subcategory,
        protocol=[contribution.protocol] if contribution.protocol else None,
        parameter_defs=contribution.parameter_defs or [],
        created_by=reviewer_id,
        db=db,
    )

    contribution.status = "approved"
    contribution.reviewer_id = reviewer_id
    contribution.promoted_template_id = promoted_id
    contribution.updated_at = datetime.now(timezone.utc)

    notif = Notification(
        user_id=contribution.contributor_id,
        type="contribution_approved",
        payload={
            "contribution_id": contribution.id,
            "template_id": promoted_id,
        },
    )
    db.add(notif)

    await log_action(
        db=db,
        operator_id=reviewer_id,
        action="contribution_approve",
        target_type="contribution",
        target_id=contribution.id,
        detail={"promoted_template_id": promoted_id},
    )
    return promoted_id


async def reject_contribution(
    contribution: TemplateContribution,
    reviewer_id: str,
    comment: str,
    db: AsyncSession,
) -> None:
    contribution.status = "rejected"
    contribution.reviewer_id = reviewer_id
    contribution.reviewer_comment = comment
    contribution.updated_at = datetime.now(timezone.utc)

    notif = Notification(
        user_id=contribution.contributor_id,
        type="contribution_rejected",
        payload={"contribution_id": contribution.id, "comment": comment},
    )
    db.add(notif)

    await log_action(
        db=db,
        operator_id=reviewer_id,
        action="contribution_reject",
        target_type="contribution",
        target_id=contribution.id,
        detail={"comment": comment},
    )


async def request_revision(
    contribution: TemplateContribution,
    reviewer_id: str,
    comment: str,
    db: AsyncSession,
) -> None:
    contribution.status = "needs_revision"
    contribution.reviewer_id = reviewer_id
    contribution.reviewer_comment = comment
    contribution.updated_at = datetime.now(timezone.utc)

    notif = Notification(
        user_id=contribution.contributor_id,
        type="needs_revision",
        payload={"contribution_id": contribution.id, "comment": comment},
    )
    db.add(notif)
