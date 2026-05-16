from __future__ import annotations
from pydantic import BaseModel, Field


class TemplateSelectionOutput(BaseModel):
    template_id: str
    # 允许 int/str/float — LLM 提取的 signal_width 等参数本身可能是数字类型
    param_mapping: dict
    confidence: float


class ScenarioParam(BaseModel):
    name: str
    description: str
    required: bool = True


class Scenario(BaseModel):
    id: str
    name: str
    description: str
    params: list[ScenarioParam]
    template: str


class ScenariosResponse(BaseModel):
    code_type: str
    scenarios: list[Scenario]


class IntentBuildRequest(BaseModel):
    code_type: str
    scenario_type: str
    params: dict[str, str]


class IntentBuildResponse(BaseModel):
    intent_text: str


# ── v3.0 IntentBuilder 多轮对话 schema ────────────────────────────────────

class IntentBuilderChatRequest(BaseModel):
    """多轮对话每轮请求。session_id 由前端生成（uuid4），首轮可传空触发后端 mint 新 id。

    P1-10：user_message 最长 8192 字符——防恶意/手抖灌爆 prompt 上下文 + Redis 存储。
    session_id 最长 128 字符——uuid4 36 字符，留余地防客户端乱构造。
    """
    session_id: str = Field(default="", max_length=128)
    user_message: str = Field(..., min_length=1, max_length=8192)
    code_type: str = Field(..., min_length=1, max_length=64)


class RAGCandidateBrief(BaseModel):
    """每轮 RAG 注入到 prompt 的 top-3 候选——精简版，前端 Card 直接渲染。"""
    template_id: str
    name: str
    description: str
    score: float


class IntentBuilderChatResponse(BaseModel):
    """多轮对话每轮响应。session_id 永远填充（首轮回填后端 mint 的新 id）。"""
    session_id: str
    assistant_message: str                # LLM 引导文本（已去除 <<intent>>...<<end>> 段）
    accumulated_intent: str               # 从 LLM 响应里抽取的累计标准化意图
    rag_candidates: list[RAGCandidateBrief]
    suggest_contribute: bool              # 5 轮 top-1 RAG 都 < 0.5 → True，前端展示贡献入口
    turn_count: int                       # 当前累计轮数（含本轮）
