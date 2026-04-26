from __future__ import annotations
import hashlib
import json
from app.core.cache import get_redis

_GENERATION_TTL = 60 * 60 * 24 * 90   # 90 days
_INTENT_TTL = 60 * 60 * 24 * 30       # 30 days


def _make_cache_key(template_id: str, version: str, params: dict) -> str:
    params_hash = hashlib.sha256(
        json.dumps(params, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    return f"gen:{template_id}:{version}:{params_hash}"


def _make_intent_key(intent_hash: str) -> str:
    return f"intent_cache:{intent_hash}"


async def get_generation_cache(template_id: str, version: str, params: dict) -> str | None:
    redis = get_redis()
    key = _make_cache_key(template_id, version, params)
    return await redis.get(key)


async def set_generation_cache(template_id: str, version: str, params: dict, code: str) -> None:
    redis = get_redis()
    key = _make_cache_key(template_id, version, params)
    await redis.set(key, code, ex=_GENERATION_TTL)


async def invalidate_template_cache(template_id: str) -> int:
    redis = get_redis()
    pattern = f"gen:{template_id}:*"
    deleted = 0
    async for key in redis.scan_iter(match=pattern, count=100):
        await redis.delete(key)
        deleted += 1
    return deleted


async def get_intent_cache(intent_hash: str) -> dict | None:
    redis = get_redis()
    raw = await redis.get(_make_intent_key(intent_hash))
    if raw:
        return json.loads(raw)
    return None


async def set_intent_cache(intent_hash: str, data: dict) -> None:
    redis = get_redis()
    await redis.set(_make_intent_key(intent_hash), json.dumps(data, ensure_ascii=False), ex=_INTENT_TTL)
