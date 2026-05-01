from __future__ import annotations
from functools import lru_cache
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    database_url: str = "postgresql+asyncpg://dvuser:dvpassword@localhost:5432/dv_platform"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Qdrant
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "templates"

    # Embedding service
    embedding_service_url: str = "http://localhost:8001"

    # LLM
    anthropic_api_key: str = ""
    llm_key_encryption_secret: str = "0" * 64

    # JWT
    jwt_secret_key: str = "change-me"
    jwt_expire_minutes: int = 10080

    # CORS
    allowed_origins: list[str] = ["http://localhost:3000"]

    # RAG thresholds
    confidence_threshold: float = 0.85
    rag_stage1_top_k: int = 100
    rag_stage2_top_k: int = 20
    rag_stage3_top_k: int = 3

    # Celery
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"
    celery_concurrency: int = 10

    # Template dedup
    template_dedup_threshold: float = 0.90

    # Backup
    backup_retain_days: int = 7
    qdrant_snapshot_enabled: bool = False

    # Super admin (for initial setup)
    super_admin_username: str = "admin"
    super_admin_password: str = "YnZn@2021"
    super_admin_email: str = "admin@example.com"

    @field_validator("jwt_secret_key")
    @classmethod
    def _validate_jwt_secret(cls, v: str) -> str:
        if v == "change-me" or len(v) < 32:
            raise ValueError(
                "jwt_secret_key must be a random string of at least 32 characters; "
                "set the JWT_SECRET_KEY environment variable."
            )
        return v

    @field_validator("llm_key_encryption_secret")
    @classmethod
    def _validate_encryption_secret(cls, v: str) -> str:
        if v == "0" * 64 or len(v) < 64:
            raise ValueError(
                "llm_key_encryption_secret must be a 64-char hex string (256-bit key); "
                "set the LLM_KEY_ENCRYPTION_SECRET environment variable."
            )
        try:
            bytes.fromhex(v[:64])
        except ValueError:
            raise ValueError("llm_key_encryption_secret must be a valid hex string.")
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
