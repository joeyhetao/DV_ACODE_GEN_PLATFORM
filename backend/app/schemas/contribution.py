from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel, Field


class ContributionCreate(BaseModel):
    """FEAT-10：必填降至 2 件（code_type + original_intent），
    template_name / description / demo_code 全部可选——缺则后端 LLM 基于 intent 生成。

    向后兼容 v3.0 4-字段路径：调用方传齐 4 字段则走原 derive_parameters_from_demo 路径，
    parameter_defs 仍可显式传（走 v2 批量导入兼容路径）。
    """
    # ── 必填 ──────────────────────────────────────────────────────
    code_type: str = Field(..., min_length=1, max_length=64)
    original_intent: str = Field(..., min_length=1, max_length=4096)
    # ── 可选（缺则 LLM 生成） ─────────────────────────────────────
    # demo_code 32KB 上限（防恶意大文件灌爆 LLM context；正常 SV 模板 <2KB）
    # description 4KB 上限（RAG 语义匹配 + LLM prompt 上下文）
    template_name: str | None = Field(default=None, max_length=256)
    description: str | None = Field(default=None, max_length=4096)
    demo_code: str | None = Field(default=None, max_length=32768)
    # ── 可选（LLM 反推或 Excel 批量入口可传） ───────────────────────
    original_row_json: dict | None = None
    category: str | None = None
    subcategory: str | None = None
    protocol: str | None = None
    keywords: list[str] | None = None
    parameter_defs: list[dict] | None = None


class ContributionPreviewRequest(BaseModel):
    """FEAT-10：POST /contributions/preview 请求体。"""
    original_intent: str = Field(..., min_length=1, max_length=4096)
    code_type: str = Field(..., min_length=1, max_length=64)


class ContributionPreviewResponse(BaseModel):
    """FEAT-10：POST /contributions/preview 响应体——LLM 生成的 5 字段 + 重名标记。"""
    template_name: str
    description: str
    demo_code: str
    parameter_defs: list[dict]
    keywords: list[str]
    name_conflict: bool = False
    existing_template_id: str | None = None           # 冲突模板的 ID，供"直接使用"跳转
    existing_template_description: str | None = None  # 冲突模板的场景描述，供用户对比判断


class ContributionUpdate(BaseModel):
    """v3.0：审核员三栏编辑覆盖到的字段全部支持 PATCH。"""
    template_name: str | None = None
    demo_code: str | None = None       # Jinja2 化模板（审核员可手改 LLM 反推结果）
    description: str | None = None
    keywords: list[str] | None = None
    parameter_defs: list[dict] | None = None
    subcategory: str | None = None
    protocol: str | None = None


class ContributionOut(BaseModel):
    id: str
    contributor_id: str
    code_type: str
    # v3.0：直接贡献入口不传 original_intent；批量 Excel 路径才有
    original_intent: str | None = None
    template_name: str
    category: str | None = None
    subcategory: str | None = None
    protocol: str | None = None
    demo_code: str
    description: str
    keywords: list[str] | None = None
    # parameter_defs 是 list[dict]——v2 schema 误声明为 dict 导致 ResponseValidationError
    parameter_defs: list[dict] | None = None
    status: str
    reviewer_comment: str | None = None
    promoted_template_id: str | None = None
    # original_row_json 是 admin 三栏审核左栏用的——前端要读 user_demo 副本
    original_row_json: dict | None = None
    created_at: datetime
    updated_at: datetime
    # FEAT-10：前端用此字段决定是否展示"立即使用"按钮（当前恒为 True）
    use_immediately_available: bool = True

    model_config = {"from_attributes": True}


class ContributionReviewAction(BaseModel):
    comment: str | None = None


class ContributionListOut(BaseModel):
    id: str
    contributor_id: str
    code_type: str
    template_name: str
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ── FEAT-4 Layer 3b：pre-approve-analysis schema ─────────────────────────────

class ConflictItem(BaseModel):
    """管理员可见的冲突描述（业务语言，不含分数）。"""
    intent: str
    current_template_name: str
    explanation: str


class PreApproveAnalysisResult(BaseModel):
    """POST /contributions/{id}/pre-approve-analysis 响应体。"""
    has_conflicts: bool
    conflicts: list[ConflictItem]
    new_corpus_preview: list[str]           # 意图短语预览（供管理员知情）
    llm_analysis: str | None = None         # 根因分析（无冲突时为 null）
    recommendation_field: str | None = None  # "description" | "keywords"
    recommendation_text: str | None = None   # 建议文本（可一键应用）
    confidence: float | None = None
    analysis_id: str                        # Redis key，approve 时关联写 DB
