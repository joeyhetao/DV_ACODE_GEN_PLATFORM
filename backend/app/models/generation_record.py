from __future__ import annotations
import uuid
from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, SmallInteger, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class GenerationRecord(Base):
    __tablename__ = "generation_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    original_intent: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_intent: Mapped[str | None] = mapped_column(Text, nullable=True)
    intent_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    rag_top3: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    template_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    template_version: Mapped[str | None] = mapped_column(String(16), nullable=True)
    params_used: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    output_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    cache_hit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    intent_cache_hit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    # L3 feedback columns (migration 006)
    feedback_rating: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    feedback_reason_tags: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    feedback_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    feedback_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 代码来源：'rag'（默认，走 RAG+模板）；'llm_direct'（FEAT-11 Stage 2 启用）
    generation_mode: Mapped[str | None] = mapped_column(String(16), nullable=True, default="rag")
    # 5 道闸触发类型：'no_matching_template' / 'off_topic' / 'under_specified'
    # / 'code_type_mismatch' / 'empty_retrieval'；正常生成路径为 None
    gate_error_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # FEAT-11 Stage 2：llm_direct 兜底记录回链至触发本次 fallback 的源 RAG 记录。
    # ondelete=SET NULL：源记录删除后保留 llm_direct 记录及其反馈数据，仅清空链。
    # 仅 generation_mode='llm_direct' 的记录会有非 None 值；'rag' 默认 None。
    parent_record_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("generation_records.id", ondelete="SET NULL"),
        nullable=True,
    )
