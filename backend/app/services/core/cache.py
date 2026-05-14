from __future__ import annotations
import hashlib
import json
from app.core.cache import get_redis

_GENERATION_TTL = 60 * 60 * 24 * 90   # 90 days
_INTENT_TTL = 60 * 60 * 24 * 30       # 30 days


def _make_cache_key(template_id: str, version: str, params: dict, llm_config_id: str = "") -> str:
    params_hash = hashlib.sha256(
        json.dumps(params, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    # llm_config_id 维度避免不同 LLM 配置写入的渲染结果互相覆盖。
    # 空字符串保留兼容性（测试 mock 不需要 stamp config_id）。
    cfg_tag = llm_config_id or "_"
    return f"gen:{cfg_tag}:{template_id}:{version}:{params_hash}"


def _make_intent_key(intent_hash: str, llm_config_id: str = "") -> str:
    cfg_tag = llm_config_id or "_"
    return f"intent_cache:{cfg_tag}:{intent_hash}"


async def get_generation_cache(
    template_id: str, version: str, params: dict, llm_config_id: str = ""
) -> str | None:
    redis = get_redis()
    key = _make_cache_key(template_id, version, params, llm_config_id)
    return await redis.get(key)


async def set_generation_cache(
    template_id: str, version: str, params: dict, code: str, llm_config_id: str = ""
) -> None:
    redis = get_redis()
    key = _make_cache_key(template_id, version, params, llm_config_id)
    await redis.set(key, code, ex=_GENERATION_TTL)


async def invalidate_template_cache(template_id: str) -> int:
    redis = get_redis()
    # key 结构是 gen:{llm_config_id}:{template_id}:{version}:{params_hash}
    # 用通配 * 覆盖所有 llm_config_id。
    pattern = f"gen:*:{template_id}:*"
    deleted = 0
    async for key in redis.scan_iter(match=pattern, count=100):
        await redis.delete(key)
        deleted += 1
    return deleted


async def invalidate_all_llm_caches() -> tuple[int, int]:
    """切换 default LLM / 改 default config 模型参数时调用：两层缓存全清。

    不同 LLM 对同一 intent 会返不同 (template_id, params)，复用旧缓存会让
    "切换模型"形同没切。两个前缀 (gen:*, intent_cache:*) 都 scan-delete。
    返回 (gen_deleted, intent_deleted)。
    """
    gen_deleted = await _scan_delete("gen:*")
    intent_deleted = await invalidate_all_intent_cache()
    return gen_deleted, intent_deleted


async def invalidate_all_intent_cache() -> int:
    """单清 intent_cache:*。供模板批量重导（lib_manager.py import）后调用：
    库内模板可能整体被替换，30 天 TTL 内的旧 intent→(template_id, params) 映射
    可能指向已不存在或已改 schema 的模板。整体清掉比逐条核对更稳。
    """
    return await _scan_delete("intent_cache:*")


async def _scan_delete(pattern: str) -> int:
    redis = get_redis()
    deleted = 0
    async for key in redis.scan_iter(match=pattern, count=200):
        await redis.delete(key)
        deleted += 1
    return deleted


async def get_intent_cache(intent_hash: str, llm_config_id: str = "") -> dict | None:
    redis = get_redis()
    raw = await redis.get(_make_intent_key(intent_hash, llm_config_id))
    if raw:
        return json.loads(raw)
    return None


async def set_intent_cache(intent_hash: str, data: dict, llm_config_id: str = "") -> None:
    redis = get_redis()
    await redis.set(
        _make_intent_key(intent_hash, llm_config_id),
        json.dumps(data, ensure_ascii=False),
        ex=_INTENT_TTL,
    )
