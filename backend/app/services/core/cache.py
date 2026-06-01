from __future__ import annotations
import hashlib
import json
from app.core.cache import get_redis

_GENERATION_TTL = 60 * 60 * 24 * 90   # 90 days
_INTENT_TTL = 60 * 60 * 24 * 30       # 30 days
_LLM_DIRECT_TTL = 60 * 60 * 24 * 7    # 7 days (FEAT-11 Stage 2)


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


async def invalidate_all_llm_caches() -> tuple[int, int, int]:
    """切换 default LLM / 改 default config 模型参数时调用：三层缓存全清。

    不同 LLM 对同一 intent 会返不同 (template_id, params)，复用旧缓存会让
    "切换模型"形同没切。三个前缀 (gen:*, intent_cache:*, gen_llm:*) 都 scan-delete。
    返回 (gen_deleted, intent_deleted, gen_llm_deleted)。

    FEAT-11 Stage 2：新增 gen_llm:* 前缀（llm_direct freeform 兜底缓存），同步清理。
    """
    gen_deleted = await _scan_delete("gen:*")
    intent_deleted = await invalidate_all_intent_cache()
    gen_llm_deleted = await _scan_delete("gen_llm:*")
    return gen_deleted, intent_deleted, gen_llm_deleted


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


# FEAT-11 Stage 2：llm_direct freeform 兜底缓存（gen_llm:*）
# key 结构：gen_llm:{llm_config_id}:{sha256(canonical(intent + code_type + signals + clk + rst))}
# - llm_config_id 维度避免切模型后命中旧文本（与 gen:* 同理）。
# - canonical 必须把 signals 按 name 排序，避免顺序差异导致同输入打不到同 key。
# - signals 用 ensure_ascii=False + (",", ":") 紧凑分隔确保字符串稳定；非排序字段
#   保持 sort_keys=True 让同一 dict 的不同插入序也归一化。


def _canonical_llm_direct_signature(
    intent: str,
    code_type: str,
    signals: list[dict],
    clk: str,
    rst: str,
) -> str:
    """规范化 llm_direct 缓存输入为单串，sha256 后入 key。

    signals 按 name 排序：用户在 GenerateForm 增/删/拖拽顺序不应影响命中。
    None / 缺 name 的项按空字符串排序兜底，保证函数总能产出确定结果。
    """
    safe_signals = sorted(
        (s for s in (signals or []) if isinstance(s, dict)),
        key=lambda s: str(s.get("name", "")),
    )
    canonical = json.dumps(
        {
            "intent": intent or "",
            "code_type": code_type or "",
            "clk": clk or "",
            "rst": rst or "",
            "signals": safe_signals,
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _make_llm_direct_key(signature: str, llm_config_id: str = "") -> str:
    cfg_tag = llm_config_id or "_"
    return f"gen_llm:{cfg_tag}:{signature}"


async def get_llm_direct_cache(
    intent: str,
    code_type: str,
    signals: list[dict],
    clk: str,
    rst: str,
    llm_config_id: str = "",
) -> str | None:
    redis = get_redis()
    sig = _canonical_llm_direct_signature(intent, code_type, signals, clk, rst)
    return await redis.get(_make_llm_direct_key(sig, llm_config_id))


async def set_llm_direct_cache(
    intent: str,
    code_type: str,
    signals: list[dict],
    clk: str,
    rst: str,
    code: str,
    llm_config_id: str = "",
) -> None:
    redis = get_redis()
    sig = _canonical_llm_direct_signature(intent, code_type, signals, clk, rst)
    await redis.set(_make_llm_direct_key(sig, llm_config_id), code, ex=_LLM_DIRECT_TTL)


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
