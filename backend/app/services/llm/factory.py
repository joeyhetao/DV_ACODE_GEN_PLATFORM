from __future__ import annotations
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.security import decrypt_api_key
from app.services.llm.base import LLMClient
from app.services.llm.anthropic_client import AnthropicLLMClient
from app.services.llm.openai_compat_client import OpenAICompatLLMClient


async def get_default_llm_client(db: AsyncSession) -> LLMClient:
    from app.models.llm_config import LLMConfig

    result = await db.execute(
        select(LLMConfig).where(LLMConfig.is_default == True, LLMConfig.is_active == True)
    )
    config = result.scalar_one_or_none()
    if config is None:
        raise RuntimeError("没有可用的 LLM 配置，请在 Admin UI 中添加并设为默认")

    return _build_client(config)


def _build_client(config, api_key: str | None = None) -> LLMClient:
    if api_key is None:
        api_key = decrypt_api_key(config.api_key_encrypted)

    if config.provider == "anthropic":
        client: LLMClient = AnthropicLLMClient(
            api_key=api_key,
            model_id=config.model_id,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
        )
    else:
        client = OpenAICompatLLMClient(
            api_key=api_key,
            model_id=config.model_id,
            base_url=config.base_url,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            output_mode=config.output_mode,
            step2_disable_thinking=config.step2_disable_thinking,
        )
    # 盖 config_id 让缓存层能按 LLM 配置维度分桶；test mock 不 stamp 此属性时
    # 调用方 getattr(..., "config_id", "") 兜底为 "_"。
    client.config_id = config.id  # type: ignore[attr-defined]
    return client


async def get_llm_client_by_id(config_id: str, db: AsyncSession) -> LLMClient:
    from app.models.llm_config import LLMConfig

    result = await db.execute(select(LLMConfig).where(LLMConfig.id == config_id))
    config = result.scalar_one_or_none()
    if config is None:
        raise ValueError(f"LLM 配置不存在: {config_id}")
    return _build_client(config)


async def get_default_llm_config_id(db: AsyncSession) -> str:
    """轻量版：只查 id，不构造客户端。pipeline_render 用来给 cache key 分桶。"""
    from app.models.llm_config import LLMConfig

    result = await db.execute(
        select(LLMConfig.id).where(LLMConfig.is_default == True, LLMConfig.is_active == True)
    )
    cfg_id = result.scalar_one_or_none()
    return cfg_id or ""
