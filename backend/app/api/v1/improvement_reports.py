"""FEAT-12：用户对比报告端点。

5 条路由：
1. POST /improvement-reports                      所有 logged-in
2. GET  /improvement-reports/check                所有 logged-in
3. GET  /admin/improvement-reports                lib_admin / super_admin
4. GET  /admin/improvement-reports/{id}           admin only
5. PATCH /admin/improvement-reports/{id}          admin only

unique 冲突 409 detail.type="duplicate_report"，FK 缺失 422
detail.type="invalid_record_ref"，非法状态跳转 422
detail.type="illegal_status_transition"。
"""
from __future__ import annotations
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user, require_role
from app.models.generation_record import GenerationRecord
from app.models.improvement_report import ImprovementReport
from app.models.template import Template
from app.models.user import User
from app.schemas.improvement_report import (
    CheckExistsResponse,
    GenerationRecordForReport,
    ImprovementReportAdminListItem,
    ImprovementReportCreate,
    ImprovementReportCreated,
    ImprovementReportDetail,
    ImprovementReportPatch,
    ReportCategoryEnum,
    ReportStatusEnum,
    is_legal_transition,
)

user_router = APIRouter(prefix="/improvement-reports", tags=["improvement_reports"])
admin_router = APIRouter(
    prefix="/admin/improvement-reports", tags=["improvement_reports_admin"]
)


# ── 用户端 ───────────────────────────────────────────────────────

@user_router.post(
    "",
    response_model=ImprovementReportCreated,
    status_code=status.HTTP_201_CREATED,
)
async def create_improvement_report(
    payload: ImprovementReportCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ImprovementReportCreated:
    rag = await db.get(GenerationRecord, payload.rag_record_id)
    llm = await db.get(GenerationRecord, payload.llm_direct_record_id)
    if rag is None or llm is None:
        raise HTTPException(
            status_code=422,
            detail={
                "type": "invalid_record_ref",
                "message": "rag_record_id 或 llm_direct_record_id 不存在",
            },
        )

    # 归属权校验：普通用户只能对自己的记录提交报告；admin 可代为提交（审核场景）。
    # 拒绝以 IDOR/BAC 探测他人 record 的 UUID 配对状态。
    is_admin = current_user.role in ("lib_admin", "super_admin")
    if not is_admin and (
        rag.user_id != current_user.id or llm.user_id != current_user.id
    ):
        raise HTTPException(
            status_code=403,
            detail={
                "type": "forbidden_record_ownership",
                "message": "只能对自己的生成记录提交对比报告",
            },
        )

    report = ImprovementReport(
        rag_record_id=payload.rag_record_id,
        llm_direct_record_id=payload.llm_direct_record_id,
        reporter_user_id=current_user.id,
        report_categories=(
            [c.value for c in payload.report_categories]
            if payload.report_categories
            else None
        ),
        reporter_note=payload.reporter_note,
        status="pending",
    )
    db.add(report)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        existing = (
            await db.execute(
                select(ImprovementReport).where(
                    ImprovementReport.rag_record_id == payload.rag_record_id,
                    ImprovementReport.llm_direct_record_id
                    == payload.llm_direct_record_id,
                )
            )
        ).scalar_one_or_none()
        # TOCTOU 兜底：极小概率冲突行在 rollback 与 SELECT 间被并发删除；
        # existing 可能为 None。返 "unknown" 占位让前端拿到非空字符串。
        raise HTTPException(
            status_code=409,
            detail={
                "type": "duplicate_report",
                "existing_report_id": existing.id if existing else "unknown",
                "message": "已有人对此对生成结果提交过对比报告",
            },
        )
    await db.refresh(report)
    return ImprovementReportCreated(id=report.id, status=ReportStatusEnum(report.status))


@user_router.get("/check", response_model=CheckExistsResponse)
async def check_report_exists(
    rag_record_id: str = Query(...),
    llm_direct_record_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> CheckExistsResponse:
    """轻查询：前端 result 阶段 mount 时调用，决定按钮 disabled 状态。

    统一返 200；exists=true 携 report_id，false 时 report_id=None。

    归属权校验：普通用户只能查询自己的 record 对；admin 可查询任意。防止
    用任意 record UUID 对探测他人 record 的对比报告存在状态。
    """
    is_admin = current_user.role in ("lib_admin", "super_admin")
    if not is_admin:
        rag = await db.get(GenerationRecord, rag_record_id)
        llm = await db.get(GenerationRecord, llm_direct_record_id)
        # 不存在或不属于当前用户：统一返 exists=false，不泄露存在性
        if rag is None or llm is None or rag.user_id != current_user.id or llm.user_id != current_user.id:
            return CheckExistsResponse(exists=False, report_id=None)

    existing = (
        await db.execute(
            select(ImprovementReport.id).where(
                ImprovementReport.rag_record_id == rag_record_id,
                ImprovementReport.llm_direct_record_id == llm_direct_record_id,
            )
        )
    ).scalar_one_or_none()
    return CheckExistsResponse(exists=existing is not None, report_id=existing)


# ── admin 端 ─────────────────────────────────────────────────────

@admin_router.get("", response_model=list[ImprovementReportAdminListItem])
async def admin_list_reports(
    status: ReportStatusEnum | None = Query(None),
    categories: list[ReportCategoryEnum] | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("lib_admin", "super_admin")),
) -> list[ImprovementReportAdminListItem]:
    """分页 + status / categories 过滤。

    categories 多选时取并集（JSONB ?| array[...]，命中任意 slug 即返）。
    join users / generation_records / templates 拿摘要字段。
    """
    stmt = (
        select(
            ImprovementReport,
            User.username,
            GenerationRecord.template_id,
            Template.name,
        )
        .join(User, User.id == ImprovementReport.reporter_user_id)
        .outerjoin(GenerationRecord, GenerationRecord.id == ImprovementReport.rag_record_id)
        .outerjoin(Template, Template.id == GenerationRecord.template_id)
        .order_by(ImprovementReport.created_at.desc())
    )
    if status is not None:
        stmt = stmt.where(ImprovementReport.status == status.value)
    if categories:
        # 报告 categories 与查询 slug 数组交集非空即命中。
        # JSONB @> '["slug"]' 命中条件下用 OR 合并：跨方言兼容（不依赖 ?| 操作符）。
        conditions = [
            ImprovementReport.report_categories.contains([c.value]) for c in categories
        ]
        stmt = stmt.where(or_(*conditions))
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    rows = (await db.execute(stmt)).all()
    return [
        ImprovementReportAdminListItem(
            id=r.id,
            status=ReportStatusEnum(r.status),
            reporter_username=username,
            rag_template_id=template_id,
            rag_template_name=template_name,
            categories=r.report_categories,
            created_at=r.created_at,
        )
        for (r, username, template_id, template_name) in rows
    ]


def _generation_record_to_schema(
    record: GenerationRecord | None, template_name: str | None
) -> GenerationRecordForReport:
    """generation_record + 关联 template_name → 三列卡片字段。

    record 为空（FK SET NULL / 删除）时返一个全空占位对象，前端按字段缺失处理。
    """
    if record is None:
        return GenerationRecordForReport(id="", output_code=None)
    return GenerationRecordForReport(
        id=record.id,
        output_code=record.output_code,
        template_id=record.template_id,
        template_name=template_name,
        params_used=record.params_used,
        original_intent=record.original_intent,
        generation_mode=record.generation_mode,
        cache_hit=record.cache_hit,
    )


@admin_router.get("/{report_id}", response_model=ImprovementReportDetail)
async def admin_get_report(
    report_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("lib_admin", "super_admin")),
) -> ImprovementReportDetail:
    report = await db.get(ImprovementReport, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="report 不存在")

    reporter = await db.get(User, report.reporter_user_id)
    rag_record = await db.get(GenerationRecord, report.rag_record_id)
    llm_record = await db.get(GenerationRecord, report.llm_direct_record_id)

    template_ids = [
        r.template_id for r in (rag_record, llm_record) if r is not None and r.template_id
    ]
    template_name_map: dict[str, str] = {}
    if template_ids:
        rows = (
            await db.execute(
                select(Template.id, Template.name).where(Template.id.in_(template_ids))
            )
        ).all()
        template_name_map = {tid: name for tid, name in rows}

    return ImprovementReportDetail(
        id=report.id,
        status=ReportStatusEnum(report.status),
        reporter_user_id=report.reporter_user_id,
        reporter_username=reporter.username if reporter else None,
        report_categories=report.report_categories,
        reporter_note=report.reporter_note,
        admin_note=report.admin_note,
        rag_record=_generation_record_to_schema(
            rag_record,
            template_name_map.get(rag_record.template_id) if rag_record else None,
        ),
        llm_direct_record=_generation_record_to_schema(
            llm_record,
            template_name_map.get(llm_record.template_id) if llm_record else None,
        ),
        created_at=report.created_at,
        updated_at=report.updated_at,
    )


@admin_router.patch("/{report_id}", response_model=ImprovementReportDetail)
async def admin_patch_report(
    report_id: str,
    payload: ImprovementReportPatch,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("lib_admin", "super_admin")),
) -> ImprovementReportDetail:
    """state machine 仅允许 pending→in_review 与 in_review→resolved。

    单独传 admin_note（不带 status）允许任何当前状态下更新；
    传 status 时校验 transition，非法返 422 illegal_status_transition。
    """
    report = await db.get(ImprovementReport, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="report 不存在")

    if payload.status is not None:
        target = payload.status.value
        if not is_legal_transition(report.status, target):
            raise HTTPException(
                status_code=422,
                detail={
                    "type": "illegal_status_transition",
                    "current": report.status,
                    "target": target,
                    "message": (
                        f"不允许的状态跳转：{report.status} → {target}；"
                        "仅允许 pending→in_review 和 in_review→resolved"
                    ),
                },
            )
        report.status = target

    if payload.admin_note is not None:
        report.admin_note = payload.admin_note

    report.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(report)

    # 复用详情端点的 join 逻辑构造响应
    return await admin_get_report(report.id, db=db, current_user=current_user)


# 复合 router：mount 时挂载两个独立 APIRouter
router = APIRouter()
router.include_router(user_router)
router.include_router(admin_router)
