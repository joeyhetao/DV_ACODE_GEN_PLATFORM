from __future__ import annotations
import re
from pydantic import BaseModel, field_validator

_SIGNAL_NAME_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')


class SignalInfo(BaseModel):
    name: str
    width: int
    role: str

    @field_validator("name")
    @classmethod
    def _validate_signal_name(cls, v: str) -> str:
        if not _SIGNAL_NAME_RE.match(v):
            raise ValueError(f"信号名 '{v}' 包含非法字符，只允许字母、数字和下划线，且不能以数字开头")
        return v


class GenerateRequest(BaseModel):
    text: str
    code_type: str
    protocol: str | None = None
    clk: str = "clk"
    rst: str = "rst_n"
    rst_polarity: str = "低有效"
    signals: list[SignalInfo] = []


class RAGCandidate(BaseModel):
    template_id: str
    name: str
    score: float


class GenerateResponse(BaseModel):
    status: str
    confidence: float | None = None
    template_id: str | None = None
    template_version: str | None = None
    cache_hit: bool = False
    intent_cache_hit: bool = False
    rag_candidates: list[RAGCandidate] = []
    params_used: dict | None = None
    extracted_params: dict | None = None
    code: str | None = None


class RenderRequest(BaseModel):
    template_id: str
    template_version: str
    params: dict


class RenderResponse(BaseModel):
    code: str


class BatchUploadResponse(BaseModel):
    job_id: str
    total_rows: int
    code_type: str
    status: str


class BatchStatusResponse(BaseModel):
    job_id: str
    status: str
    total_rows: int
    completed_rows: int
    progress: float
    result_url: str | None = None
    error_message: str | None = None


class PreflightRowResult(BaseModel):
    row_id: str
    estimated_confidence: float
    top_match: dict | None = None


class PreflightResponse(BaseModel):
    results: list[PreflightRowResult]
