from __future__ import annotations
import uuid
from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class TemplateCorpusCase(Base):
    __tablename__ = "template_corpus_cases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    intent: Mapped[str] = mapped_column(Text, nullable=False)
    code_type: Mapped[str] = mapped_column(String(16), nullable=False)
    expected_template_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("templates.id", ondelete="CASCADE"), nullable=False
    )
    source: Mapped[str] = mapped_column(
        String(32), nullable=False, default="auto_generated"
    )
    auto_generated_from: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("template_contributions.id", ondelete="SET NULL"), nullable=True
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
