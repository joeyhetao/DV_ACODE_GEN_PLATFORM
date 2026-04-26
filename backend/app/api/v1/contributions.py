from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.security import get_current_user, require_role
from app.models.user import User
from app.models.contribution import TemplateContribution
from app.schemas.contribution import (
    ContributionCreate,
    ContributionUpdate,
    ContributionOut,
    ContributionListOut,
    ContributionReviewAction,
)
from app.services.platform.contribution_service import (
    approve_contribution,
    reject_contribution,
    request_revision,
)

router = APIRouter(prefix="/contributions", tags=["contributions"])


@router.post("", response_model=ContributionOut, status_code=201)
async def submit_contribution(
    payload: ContributionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    contribution = TemplateContribution(
        contributor_id=current_user.id,
        code_type=payload.code_type,
        original_intent=payload.original_intent,
        original_row_json=payload.original_row_json,
        template_name=payload.template_name,
        subcategory=payload.subcategory,
        protocol=payload.protocol,
        demo_code=payload.demo_code,
        description=payload.description,
        keywords=payload.keywords,
        parameter_defs=payload.parameter_defs,
        status="pending",
    )
    db.add(contribution)
    await db.commit()
    await db.refresh(contribution)
    return contribution


@router.get("/my", response_model=list[ContributionListOut])
async def my_contributions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = (
        select(TemplateContribution)
        .where(TemplateContribution.contributor_id == current_user.id)
        .order_by(TemplateContribution.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(stmt)
    return result.scalars().all()


# Admin routes must be registered before /{contribution_id} to avoid path shadowing
@router.get("/admin/all", response_model=list[ContributionListOut])
async def admin_list_contributions(
    status: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("lib_admin", "super_admin")),
):
    stmt = select(TemplateContribution).order_by(TemplateContribution.created_at.desc())
    if status:
        stmt = stmt.where(TemplateContribution.status == status)
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/{contribution_id}", response_model=ContributionOut)
async def get_contribution(
    contribution_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    contribution = await db.get(TemplateContribution, contribution_id)
    if not contribution:
        raise HTTPException(status_code=404, detail="贡献不存在")
    if (
        contribution.contributor_id != current_user.id
        and current_user.role not in ("lib_admin", "super_admin")
    ):
        raise HTTPException(status_code=403, detail="无权访问")
    return contribution


@router.patch("/{contribution_id}", response_model=ContributionOut)
async def update_contribution(
    contribution_id: str,
    payload: ContributionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    contribution = await db.get(TemplateContribution, contribution_id)
    if not contribution:
        raise HTTPException(status_code=404, detail="贡献不存在")
    if contribution.contributor_id != current_user.id:
        raise HTTPException(status_code=403, detail="只能修改自己的贡献")
    if contribution.status not in ("pending", "needs_revision"):
        raise HTTPException(status_code=400, detail="该状态下不允许修改")

    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(contribution, field, value)

    from datetime import datetime, timezone
    contribution.updated_at = datetime.now(timezone.utc)
    contribution.status = "pending"
    await db.commit()
    await db.refresh(contribution)
    return contribution


@router.post("/{contribution_id}/approve")
async def admin_approve(
    contribution_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("lib_admin", "super_admin")),
):
    contribution = await db.get(TemplateContribution, contribution_id)
    if not contribution:
        raise HTTPException(status_code=404, detail="贡献不存在")
    if contribution.status != "pending":
        raise HTTPException(status_code=400, detail="只能审批 pending 状态的贡献")

    from app.api.v1.templates import _create_template_from_contribution

    promoted_id = await approve_contribution(
        contribution=contribution,
        reviewer_id=current_user.id,
        db=db,
        template_create_fn=_create_template_from_contribution,
    )
    await db.commit()
    return {"status": "approved", "promoted_template_id": promoted_id}


@router.post("/{contribution_id}/reject")
async def admin_reject(
    contribution_id: str,
    payload: ContributionReviewAction,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("lib_admin", "super_admin")),
):
    contribution = await db.get(TemplateContribution, contribution_id)
    if not contribution:
        raise HTTPException(status_code=404, detail="贡献不存在")
    if contribution.status not in ("pending", "needs_revision"):
        raise HTTPException(status_code=400, detail="该状态不可拒绝")

    await reject_contribution(
        contribution=contribution,
        reviewer_id=current_user.id,
        comment=payload.comment or "",
        db=db,
    )
    await db.commit()
    return {"status": "rejected"}


@router.post("/{contribution_id}/request-revision")
async def admin_request_revision(
    contribution_id: str,
    payload: ContributionReviewAction,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("lib_admin", "super_admin")),
):
    contribution = await db.get(TemplateContribution, contribution_id)
    if not contribution:
        raise HTTPException(status_code=404, detail="贡献不存在")
    if contribution.status != "pending":
        raise HTTPException(status_code=400, detail="只能对 pending 状态请求修改")

    await request_revision(
        contribution=contribution,
        reviewer_id=current_user.id,
        comment=payload.comment or "",
        db=db,
    )
    await db.commit()
    return {"status": "needs_revision"}
