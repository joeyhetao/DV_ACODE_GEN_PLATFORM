from __future__ import annotations
from datetime import datetime
from typing import Literal
from pydantic import BaseModel


# FEAT-13 生产门控的三档枚举，与 ORM 列 `maturity_level` 一致；非法值由 Pydantic 422 拦。
MaturityLevel = Literal["production", "experimental", "draft"]


class ParameterDef(BaseModel):
    name: str
    type: str
    required: bool = True
    description: str = ""
    default: str | None = None
    role_hint: str | None = None


class TemplateCreate(BaseModel):
    id: str
    version: str = "1.0.0"
    name: str
    code_type: str
    subcategory: str | None = None
    protocol: list[str] | None = None
    tags: list[str] | None = None
    keywords: list[str] | None = None
    description: str
    parameters: list[dict]
    template_body: str
    maturity: str = "draft"
    maturity_level: MaturityLevel = "experimental"
    related_ids: list[str] | None = None


class TemplateUpdate(BaseModel):
    version: str | None = None
    name: str | None = None
    description: str | None = None
    parameters: list[dict] | None = None
    template_body: str | None = None
    maturity: str | None = None
    # FEAT-13 生产门控等级：仅 super_admin 可改（templates.update_template 端点校验）；
    # 非法值由 Literal 自动 422。
    maturity_level: MaturityLevel | None = None
    tags: list[str] | None = None
    keywords: list[str] | None = None
    related_ids: list[str] | None = None
    change_note: str | None = None


class TemplateOut(BaseModel):
    id: str
    version: str
    name: str
    code_type: str
    subcategory: str | None
    protocol: list[str] | None
    tags: list[str] | None
    keywords: list[str] | None
    description: str
    parameters: list[dict]
    template_body: str
    maturity: str
    maturity_level: MaturityLevel
    is_active: bool
    related_ids: list[str] | None
    sync_status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TemplateListOut(BaseModel):
    id: str
    name: str
    code_type: str
    subcategory: str | None
    protocol: list[str] | None
    description: str
    maturity: str
    maturity_level: MaturityLevel
    is_active: bool
    updated_at: datetime

    model_config = {"from_attributes": True}


class DuplicateWarning(BaseModel):
    status: str = "duplicate_warning"
    similar_templates: list[dict]


class ImportResult(BaseModel):
    imported: int
    skipped_duplicate: int
    skipped_name_conflict: int
    failed: int
    details: list[dict]
