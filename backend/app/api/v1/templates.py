from __future__ import annotations
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.database import get_db
from app.core.security import get_current_user, require_role
from app.models.user import User
from app.models.template import Template, TemplateVersion
from app.schemas.template import TemplateOut, TemplateListOut, TemplateCreate, TemplateUpdate, DuplicateWarning
from app.services.core.dedup import check_name_duplicate, check_semantic_duplicate
from app.services.core.renderer import validate_template_syntax
from app.services.core.cache import invalidate_template_cache

router = APIRouter(prefix="/templates", tags=["templates"])


async def _create_template_from_contribution(
    name: str,
    code_type: str,
    description: str,
    template_body: str,
    keywords: list[str],
    subcategory: str | None,
    protocol: list[str] | None,
    parameter_defs: list[dict],
    created_by: str,
    db: AsyncSession,
) -> str:
    import uuid
    template_id = f"contrib_{uuid.uuid4().hex[:12]}"
    template = Template(
        id=template_id,
        version="1.0.0",
        name=name,
        code_type=code_type,
        subcategory=subcategory,
        protocol=protocol,
        keywords=keywords,
        description=description,
        parameters=parameter_defs,
        template_body=template_body,
        maturity="draft",
        created_by=created_by,
        sync_status="pending",
    )
    db.add(template)
    await db.flush()
    return template_id


@router.get("", response_model=list[TemplateListOut])
async def list_templates(
    code_type: Optional[str] = None,
    subcategory: Optional[str] = None,
    maturity: Optional[str] = None,
    keyword: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(Template).where(Template.is_active == True)
    if code_type:
        stmt = stmt.where(Template.code_type == code_type)
    if subcategory:
        stmt = stmt.where(Template.subcategory == subcategory)
    if maturity:
        stmt = stmt.where(Template.maturity == maturity)
    if keyword:
        stmt = stmt.where(
            Template.keywords.any(keyword) | Template.name.ilike(f"%{keyword}%")
        )
    stmt = stmt.order_by(Template.updated_at.desc())
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/{template_id}", response_model=TemplateOut)
async def get_template(
    template_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    template = await db.get(Template, template_id)
    if not template or not template.is_active:
        raise HTTPException(status_code=404, detail="模板不存在")
    return template


@router.get("/{template_id}/versions")
async def list_versions(
    template_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(TemplateVersion)
        .where(TemplateVersion.template_id == template_id)
        .order_by(TemplateVersion.created_at.desc())
    )
    versions = result.scalars().all()
    return [{"version": v.version, "created_at": v.created_at, "snapshot": v.snapshot} for v in versions]


@router.post("", status_code=201)
async def create_template(
    payload: TemplateCreate,
    force: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("lib_admin", "super_admin")),
):
    if await check_name_duplicate(db, payload.name):
        raise HTTPException(status_code=409, detail="模板名称已存在")

    validate_template_syntax(payload.template_body)

    if not force:
        similar = await check_semantic_duplicate(
            description=payload.description,
            name=payload.name,
            tags=payload.tags,
            keywords=payload.keywords,
        )
        if similar:
            return DuplicateWarning(similar_templates=similar)

    from datetime import datetime, timezone
    template = Template(
        id=payload.id,
        version=payload.version,
        name=payload.name,
        code_type=payload.code_type,
        subcategory=payload.subcategory,
        protocol=payload.protocol,
        tags=payload.tags,
        keywords=payload.keywords,
        description=payload.description,
        parameters=payload.parameters,
        template_body=payload.template_body,
        maturity=payload.maturity,
        related_ids=payload.related_ids,
        created_by=current_user.id,
        sync_status="pending",
    )
    db.add(template)
    await db.commit()
    await db.refresh(template)
    return template


@router.patch("/{template_id}", response_model=TemplateOut)
async def update_template(
    template_id: str,
    payload: TemplateUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("lib_admin", "super_admin")),
):
    template = await db.get(Template, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")

    snapshot = {
        "version": template.version,
        "name": template.name,
        "description": template.description,
        "parameters": template.parameters,
        "template_body": template.template_body,
    }
    ver_record = TemplateVersion(
        template_id=template_id,
        version=template.version,
        snapshot=snapshot,
        change_note=payload.change_note,
    )
    db.add(ver_record)

    for field, value in payload.model_dump(exclude_none=True, exclude={"change_note"}).items():
        setattr(template, field, value)

    if payload.template_body:
        validate_template_syntax(payload.template_body)

    from datetime import datetime, timezone
    template.updated_at = datetime.now(timezone.utc)
    template.sync_status = "pending"

    await invalidate_template_cache(template_id)
    await db.commit()
    await db.refresh(template)
    return template


@router.delete("/{template_id}", status_code=204)
async def delete_template(
    template_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("lib_admin", "super_admin")),
):
    template = await db.get(Template, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")
    template.is_active = False
    await invalidate_template_cache(template_id)
    await db.commit()
