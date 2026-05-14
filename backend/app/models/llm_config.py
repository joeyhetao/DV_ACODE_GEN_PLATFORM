from __future__ import annotations
import uuid
from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, Enum, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class LLMConfig(Base):
    __tablename__ = "llm_configs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(
        Enum("anthropic", "openai_compatible", name="llm_provider_enum"),
        nullable=False,
    )
    base_url: Mapped[str | None] = mapped_column(String(256), nullable=True)
    api_key_encrypted: Mapped[str] = mapped_column(String(512), nullable=False)
    model_id: Mapped[str] = mapped_column(String(128), nullable=False)
    output_mode: Mapped[str] = mapped_column(
        Enum("tool_calling", "json_mode", "prompt_json", name="output_mode_enum"),
        nullable=False,
        default="tool_calling",
    )
    temperature: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    max_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=512)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # 仅 OpenAI 兼容 provider 生效（智谱 GLM / DeepSeek 系）；Anthropic 走 extended_thinking 不受此控制。
    # 默认 True：实测 GLM-4.7 step2 thinking ON 单次 12-249s，禁后 ~3s（ARCHITECTURE.md §3.12.2）。
    step2_disable_thinking: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true",
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
