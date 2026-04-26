from __future__ import annotations
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.services.core.cache import get_intent_cache, set_intent_cache


async def lookup_history(intent_hash: str) -> dict | None:
    return await get_intent_cache(intent_hash)


async def save_history(
    intent_hash: str,
    template_id: str,
    param_mapping: dict,
    confidence: float,
    code: str,
) -> None:
    data = {
        "template_id": template_id,
        "param_mapping": param_mapping,
        "confidence": confidence,
        "code": code,
    }
    await set_intent_cache(intent_hash, data)
