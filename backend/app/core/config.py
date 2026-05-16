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
    # 维度必须匹配 EMBED_MODEL 实际输出（bge-m3=1024, bge-large-en-v1.5=1024,
    # Qwen3-Embedding-4B=2560）。换模型时同步改本字段；启动时若 Qdrant 中已存在
    # 的 collection 维度与本设置不一致，main.py:_init_qdrant_collection 将日志告警。
    embedding_dim: int = 1024

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

    # Off-topic intent gate：原文 → bge-m3 dense → Qdrant top1 余弦 < 阈值 → 422 早返。
    # 阈值由 backend/scripts/calibrate_offtopic_threshold.py 在 offtopic_corpus.yaml 上校准得出。
    # 0.44 当前校准结果：off_max=0.4315 / marg_min=0.4516，gap=0.02。
    # OFFTOPIC_GATE_ENABLED=false 一键关闸退回老行为（紧急逃生通道）。
    offtopic_gate_enabled: bool = True
    offtopic_dense_threshold: float = 0.44

    # Code-type 一致性闸：紧跟 off-topic 之后。dense 跨 code_type 比较，若用户选的
    # code_type 在 dense top1 上显著输给另一类（gap ≥ margin），抛 422 提示改类型。
    # 典型反例："统计 ... 覆盖率"选了 assertion → coverage 库 dense 0.76 vs 当前 0.62。
    # margin 凭经验，可按 corpus 校准；初值 0.10 已经能区分明显错配同时不误伤模糊场景。
    code_type_mismatch_gate_enabled: bool = True
    code_type_mismatch_margin: float = 0.10

    # Under-specified intent 闸（契约反转 v2.11）：必填参数缺少高置信源（落在
    # semantic_fallback / placeholder / 或 LLM 返 trivial 值）时直接 422，
    # 不再编占位符兜底渲染。让用户知道具体缺哪些信息再补充。
    # 关闸：UNDER_SPECIFIED_GATE_ENABLED=false 退回旧"始终返代码"行为。
    under_specified_gate_enabled: bool = True

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
