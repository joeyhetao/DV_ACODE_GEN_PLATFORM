from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel


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
    related_ids: list[str] | None = None


class TemplateUpdate(BaseModel):
    version: str | None = None
    name: str | None = None
    description: str | None = None
    parameters: list[dict] | None = None
    template_body: str | None = None
    maturity: str | None = None
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
