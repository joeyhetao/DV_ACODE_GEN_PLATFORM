from __future__ import annotations
import uuid
from datetime import datetime, timezone
from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class ImprovementReport(Base):
    """FEAT-12：用户对比报告。
    一对 (rag_record_id, llm_direct_record_id) 仅允许一份；status 走三态状态机
    pending → in_review → resolved。
    """

    __tablename__ = "improvement_reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    rag_record_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("generation_records.id", ondelete="CASCADE"),
        nullable=False,
    )
    llm_direct_record_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("generation_records.id", ondelete="CASCADE"),
        nullable=False,
    )
    reporter_user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    report_categories: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    reporter_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        Enum("pending", "in_review", "resolved", name="report_status_enum"),
        nullable=False,
        default="pending",
        # 索引由 migration 008 的复合 (status, created_at DESC) 提供；最左前缀
        # 覆盖单列 status 过滤。不在 ORM 声明 index=True，避免 alembic autogenerate
        # 误生成单列 ix_improvement_reports_status 的虚假修订。
    )
    admin_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        UniqueConstraint(
            "rag_record_id", "llm_direct_record_id", name="uq_improvement_reports_pair"
        ),
    )
