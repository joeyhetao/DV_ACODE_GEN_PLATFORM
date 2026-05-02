from __future__ import annotations
import re
from typing import Literal
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
    """两步式流程的第二步：用户确认参数后渲染。

    两种调用模式：
    - **方案 3 路径**（前端两步式 UI）：传 intent_hash + confidence + normalized_intent
      + rag_candidates，由 pipeline_render 写 GenerationRecord 与缓存
    - **legacy 重渲染路径**：仅传 template_id + template_version + params，
      不写 GenerationRecord（参考既有 /render 老用法）
    """
    template_id: str
    template_version: str
    params: dict
    # 方案 3 透传字段（前端 preview 阶段拿到后传回，让 render 完成 GenerationRecord 写入）
    intent_hash: str | None = None
    confidence: float = 0.0
    confidence_source: str = ""              # "llm_step1" | "rag_fallback" | "intent_cache"
    normalized_intent: str = ""
    original_intent: str = ""
    rag_candidates: list[dict] = []
    code_type: str = ""                      # 用于 GenerationRecord


class RenderResponse(BaseModel):
    code: str
    cache_hit: bool = False


# ── 方案 3：两步式 preview 端点 schema ──────────────────────────────────────

class ParamWithSource(BaseModel):
    """单个参数的预填充值 + 来源标识，用于前端 5 色徽标显示。"""
    value: str | int | float | list[str]
    source: Literal["signal_list", "regex", "llm", "default", "placeholder"]
    required: bool = True
    description: str = ""
    type: str = "string"                     # 模板里声明的 type（用于前端校验）


class RAGCandidateWithParams(BaseModel):
    """RAG 候选（含 parameters 列表，供前端切换模板时重新渲染表单用）。"""
    template_id: str
    name: str
    score: float
    parameters: list[dict] = []


class PreviewResponse(BaseModel):
    """两步式流程的第一步响应：模板推荐 + 参数预填充。"""
    template_id: str
    template_name: str
    template_version: str
    confidence: float
    confidence_source: Literal["llm_step1", "rag_fallback", "intent_cache"]
    rag_candidates: list[RAGCandidateWithParams]
    params: dict[str, ParamWithSource]
    intent_hash: str
    normalized_intent: str
    quick_render: bool = False               # intent_cache 命中 → True，前端跳过确认面板


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
