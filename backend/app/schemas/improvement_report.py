"""FEAT-12：用户对比报告 schemas.

ReportCategoryEnum 用英文 slug（user 已拍板）：
- wrong_template: 模板选错
- wrong_params:   参数映射错
- poor_style:     代码风格差
- other:          其他
"""
from __future__ import annotations
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class ReportCategoryEnum(str, Enum):
    WRONG_TEMPLATE = "wrong_template"
    WRONG_PARAMS = "wrong_params"
    POOR_STYLE = "poor_style"
    OTHER = "other"


class ReportStatusEnum(str, Enum):
    PENDING = "pending"
    IN_REVIEW = "in_review"
    RESOLVED = "resolved"


class ImprovementReportCreate(BaseModel):
    """POST /improvement-reports 请求体。

    categories / note 均可选；全部不填仍然合法（spec §2 AC1）。
    """
    rag_record_id: str = Field(..., min_length=1, max_length=36)
    llm_direct_record_id: str = Field(..., min_length=1, max_length=36)
    report_categories: list[ReportCategoryEnum] | None = Field(
        default=None, description="可选；4 项 enum slug 中任意子集"
    )
    reporter_note: str | None = Field(
        default=None, max_length=4096, description="可选自由文本说明"
    )


class ImprovementReportCreated(BaseModel):
    """POST /improvement-reports 201 响应。"""
    id: str
    status: ReportStatusEnum

    model_config = {"from_attributes": True}


class CheckExistsResponse(BaseModel):
    """GET /improvement-reports/check 响应。

    统一返 200：exists=true 携 report_id；exists=false 时 report_id 为 None。
    不区分 404，前端只需读 exists 即可。
    """
    exists: bool
    report_id: str | None = None


class GenerationRecordForReport(BaseModel):
    """admin 详情页三列对比中单条 generation_record 的展示字段。"""
    id: str
    output_code: str | None = None
    template_id: str | None = None
    template_name: str | None = None
    params_used: dict | None = None
    original_intent: str | None = None
    generation_mode: str | None = None
    cache_hit: bool = False


class ImprovementReportAdminListItem(BaseModel):
    """GET /admin/improvement-reports 单条摘要。"""
    id: str
    status: ReportStatusEnum
    reporter_username: str | None = None
    rag_template_name: str | None = None
    rag_template_id: str | None = None
    categories: list[str] | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ImprovementReportDetail(BaseModel):
    """GET /admin/improvement-reports/{id} 详情。"""
    id: str
    status: ReportStatusEnum
    reporter_user_id: str
    reporter_username: str | None = None
    report_categories: list[str] | None = None
    reporter_note: str | None = None
    admin_note: str | None = None
    rag_record: GenerationRecordForReport
    llm_direct_record: GenerationRecordForReport
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ImprovementReportPatch(BaseModel):
    """PATCH /admin/improvement-reports/{id} 请求体。

    status / admin_note 均可单独提供。state machine 校验在端点层（仅允许
    pending→in_review 和 in_review→resolved；非法 422 illegal_status_transition）。
    """
    status: ReportStatusEnum | None = None
    admin_note: str | None = Field(default=None, max_length=8192)


class ImprovementReportListQuery(BaseModel):
    """GET /admin/improvement-reports 查询参数（FastAPI Query 内联取代了直接使用本类；
    保留作文档用）。"""
    status: ReportStatusEnum | None = None
    categories: list[ReportCategoryEnum] | None = None
    page: int = 1
    page_size: int = 20


# 状态机：仅允许相邻一跳前进。
ALLOWED_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"in_review"},
    "in_review": {"resolved"},
    "resolved": set(),
}


def is_legal_transition(current: str, target: str) -> bool:
    """三态状态机；同状态视为合法（PATCH 仅改 admin_note 时复用此判断）。"""
    if current == target:
        return True
    return target in ALLOWED_STATUS_TRANSITIONS.get(current, set())
