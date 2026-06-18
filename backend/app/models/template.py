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
    # 旧 `maturity` 列：开发成熟度（draft/validated/production，ORM 与 migration 001
    # 的 enum 值存在历史漂移），与 FEAT-13 引入的生产门控 `maturity_level` 语义不同，
    # 两列并存，绝不能混用。
    maturity: Mapped[str] = mapped_column(
        Enum("draft", "validated", "production", name="maturity_enum"),
        nullable=False,
        default="draft",
    )
    # FEAT-13 生产门控：production 进入 RAG 召回主库；experimental / draft 仅显示在
    # admin 库，不参与召回。通过 review 的贡献模板固定 experimental，须 super_admin
    # 显式 PATCH 提升。
    maturity_level: Mapped[str] = mapped_column(
        Enum("production", "experimental", "draft", name="template_maturity_enum"),
        nullable=False,
        default="experimental",
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
