from __future__ import annotations
import hashlib
import json
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.services.core.cache import get_intent_cache, set_intent_cache


def template_params_fingerprint(parameters: list[dict] | None) -> str:
    """对 template.parameters 取稳定指纹，用于检测 intent_cache 命中时 schema 是否漂移。

    只 hash 影响"缓存 mapping 是否仍合法"的字段：name / required / expr_type。
    description / default 之类不进 fingerprint，避免文案小改就 invalidate。
    """
    items = [
        {
            "name": p.get("name"),
            "required": bool(p.get("required")),
            "expr_type": p.get("expr_type", ""),
        }
        for p in (parameters or [])
    ]
    items.sort(key=lambda x: x["name"] or "")
    return hashlib.sha256(
        json.dumps(items, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()[:16]


async def lookup_history(intent_hash: str, llm_config_id: str = "") -> dict | None:
    return await get_intent_cache(intent_hash, llm_config_id)


async def save_history(
    intent_hash: str,
    template_id: str,
    param_mapping: dict,
    confidence: float,
    code: str,
    llm_config_id: str = "",
    params_fingerprint: str = "",
    template_version: str = "",
) -> None:
    data = {
        "template_id": template_id,
        # 必须存 version：pipeline.preview 的 intent_cache 命中分支会用此值去找
        # gen:{cfg}:{tmpl_id}:{version}:{hash}。漏存 → 默认 "1" → 与实际 "1.0.0" 不匹配 →
        # gen miss → 静默 fallthrough 到完整 RAG/LLM 路径，缓存形同未命中。
        "version": template_version,
        "param_mapping": param_mapping,
        "confidence": confidence,
        "code": code,
        "params_fingerprint": params_fingerprint,
    }
    await set_intent_cache(intent_hash, data, llm_config_id)
