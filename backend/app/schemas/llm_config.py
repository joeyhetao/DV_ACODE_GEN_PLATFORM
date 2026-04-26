from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel


class LLMConfigCreate(BaseModel):
    name: str
    provider: str
    base_url: str | None = None
    api_key: str
    model_id: str
    output_mode: str = "tool_calling"
    temperature: float = 0.0
    max_tokens: int = 512
    is_active: bool = True
    is_default: bool = False


class LLMConfigUpdate(BaseModel):
    name: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    model_id: str | None = None
    output_mode: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    is_active: bool | None = None


class LLMConfigOut(BaseModel):
    id: str
    name: str
    provider: str
    base_url: str | None
    api_key_masked: str
    model_id: str
    output_mode: str
    temperature: float
    max_tokens: int
    is_active: bool
    is_default: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class LLMTestRequest(BaseModel):
    test_type: str = "basic"


class LLMTestResponse(BaseModel):
    success: bool
    latency_ms: float
    result: str | None = None
    error: str | None = None
