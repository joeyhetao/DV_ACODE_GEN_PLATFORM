from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel


class ContributionCreate(BaseModel):
    code_type: str
    original_intent: str
    original_row_json: dict | None = None
    template_name: str
    category: str | None = None
    subcategory: str | None = None
    protocol: str | None = None
    demo_code: str
    description: str
    keywords: list[str] | None = None
    parameter_defs: list[dict] | None = None


class ContributionUpdate(BaseModel):
    template_name: str | None = None
    demo_code: str | None = None
    description: str | None = None
    keywords: list[str] | None = None
    parameter_defs: list[dict] | None = None


class ContributionOut(BaseModel):
    id: str
    contributor_id: str
    code_type: str
    original_intent: str
    template_name: str
    category: str | None
    subcategory: str | None
    protocol: str | None
    demo_code: str
    description: str
    keywords: list[str] | None
    parameter_defs: dict | None
    status: str
    reviewer_comment: str | None
    promoted_template_id: str | None
    created_at: datetime
    updated_at: datetime

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
