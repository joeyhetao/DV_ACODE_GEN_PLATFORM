from __future__ import annotations
import uuid
from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, Text, ARRAY
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class Template(Base):
    __tablename__ = "templates"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    version: Mapped[str] = mapped_column(String(16), nullable=False, default="1.0.0")
    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    code_type: Mapped[str] = mapped_column(
        Enum("assertion", "coverage", name="code_type_enum"),
        nullable=False,
    )
    subcategory: Mapped[str] = mapped_column(String(64), nullable=True)
    protocol: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=True)
    tags: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=True)
    keywords: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    parameters: Mapped[dict] = mapped_column(JSONB, nullable=False, default=list)
    template_body: Mapped[str] = mapped_column(Text, nullable=False)
    maturity: Mapped[str] = mapped_column(
        Enum("draft", "validated", "production", name="maturity_enum"),
        nullable=False,
        default="draft",
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    related_ids: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=True)
    qdrant_point_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    sync_status: Mapped[str] = mapped_column(
        Enum("ok", "syncing", "sync_error", name="sync_status_enum"),
        nullable=False,
        default="ok",
    )
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
    created_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)


class TemplateVersion(Base):
    __tablename__ = "template_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    template_id: Mapped[str] = mapped_column(String(32), ForeignKey("templates.id"), nullable=False)
    version: Mapped[str] = mapped_column(String(16), nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    change_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    created_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
