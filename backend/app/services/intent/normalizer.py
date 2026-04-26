from __future__ import annotations
import hashlib
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.registry import get_registry
from app.services.llm.factory import get_default_llm_client


async def normalize_intent(original_intent: str, db: AsyncSession) -> tuple[str, str]:
    registry = get_registry()
    rules = registry.build_normalization_rules()
    llm = await get_default_llm_client(db)
    normalized = await llm.normalize_intent(original_intent, rules)
    intent_hash = hashlib.sha256(normalized.encode()).hexdigest()
    return normalized, intent_hash
