from __future__ import annotations
import time
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.security import require_role
from app.core.security import encrypt_api_key, decrypt_api_key, mask_api_key
from app.models.user import User
from app.models.llm_config import LLMConfig
from app.schemas.llm_config import LLMConfigCreate, LLMConfigUpdate, LLMConfigOut, LLMTestRequest, LLMTestResponse
from app.services.core.cache import invalidate_all_llm_caches

router = APIRouter(prefix="/admin/llm", tags=["admin-llm"])


def _to_config_out(c: LLMConfig) -> LLMConfigOut:
    # 必须先 decrypt 再 mask：mask_api_key 作用于密文 hex 只能产出无意义的"密文头尾"，
    # 用户无法识别这是哪条 key。决心解密的开销可忽略（仅在 Admin list / detail 时调）。
    try:
        plaintext = decrypt_api_key(c.api_key_encrypted) if c.api_key_encrypted else ""
    except Exception:
        # 兜底：密文损坏 / 加密 key 改了，至少别让整个 list 端点 500。
        plaintext = ""
    return LLMConfigOut(
        id=c.id, name=c.name, provider=c.provider, base_url=c.base_url,
        api_key_masked=mask_api_key(plaintext),
        model_id=c.model_id, output_mode=c.output_mode,
        temperature=c.temperature, max_tokens=c.max_tokens,
        is_active=c.is_active, is_default=c.is_default,
        step2_disable_thinking=c.step2_disable_thinking,
        created_at=c.created_at, updated_at=c.updated_at,
    )


@router.get("/configs", response_model=list[LLMConfigOut])
async def list_configs(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("super_admin")),
):
    result = await db.execute(select(LLMConfig).order_by(LLMConfig.created_at.desc()))
    configs = result.scalars().all()
    return [_to_config_out(c) for c in configs]


@router.post("/configs", response_model=LLMConfigOut, status_code=201)
async def create_config(
    payload: LLMConfigCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("super_admin")),
):
    encrypted = encrypt_api_key(payload.api_key)
    cfg = LLMConfig(
        name=payload.name,
        provider=payload.provider,
        base_url=payload.base_url,
        api_key_encrypted=encrypted,
        model_id=payload.model_id,
        output_mode=payload.output_mode,
        temperature=payload.temperature,
        max_tokens=payload.max_tokens,
        is_active=payload.is_active,
        is_default=payload.is_default,
        step2_disable_thinking=payload.step2_disable_thinking,
    )
    if payload.is_default:
        await db.execute(
            LLMConfig.__table__.update().where(LLMConfig.is_default == True).values(is_default=False)
        )
    db.add(cfg)
    await db.commit()
    await db.refresh(cfg)
    # 新建配置若立刻成为 default，旧的 gen:*/intent_cache:* 由不同 LLM 写入，必须清。
    if payload.is_default:
        await invalidate_all_llm_caches()
    return _to_config_out(cfg)


@router.patch("/configs/{config_id}", response_model=LLMConfigOut)
async def update_config(
    config_id: str,
    payload: LLMConfigUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("super_admin")),
):
    cfg = await db.get(LLMConfig, config_id)
    if not cfg:
        raise HTTPException(status_code=404, detail="配置不存在")

    # was_default 在 setattr 前快照——更新当前 default 配置本体（如改 model_id /
    # temperature / max_tokens / step2_disable_thinking）也要 flush，否则旧缓存
    # 命中后用户看到的是旧模型/旧参数的输出。
    was_default = bool(cfg.is_default)

    data = payload.model_dump(exclude_none=True)
    if "api_key" in data:
        cfg.api_key_encrypted = encrypt_api_key(data.pop("api_key"))

    becoming_default = bool(data.get("is_default"))
    if becoming_default:
        await db.execute(
            LLMConfig.__table__.update().where(LLMConfig.id != config_id).values(is_default=False)
        )

    for field, value in data.items():
        setattr(cfg, field, value)

    await db.commit()
    await db.refresh(cfg)
    if was_default or becoming_default:
        await invalidate_all_llm_caches()
    return _to_config_out(cfg)


@router.delete("/configs/{config_id}", status_code=204)
async def delete_config(
    config_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("super_admin")),
):
    cfg = await db.get(LLMConfig, config_id)
    if not cfg:
        raise HTTPException(status_code=404, detail="配置不存在")
    was_default = bool(cfg.is_default)
    await db.delete(cfg)
    await db.commit()
    if was_default:
        # 删掉的是当前 default：下一次请求会落到新 default（或 500），旧缓存无效。
        await invalidate_all_llm_caches()


@router.post("/configs/{config_id}/set-default")
async def set_default(
    config_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("super_admin")),
):
    cfg = await db.get(LLMConfig, config_id)
    if not cfg:
        raise HTTPException(status_code=404, detail="配置不存在")
    await db.execute(
        LLMConfig.__table__.update().values(is_default=False)
    )
    cfg.is_default = True
    await db.commit()
    # 切默认模型必清两层缓存：旧 LLM 命中的 (template_id, params) 在新模型下未必合法。
    await invalidate_all_llm_caches()
    return {"status": "ok", "default_config_id": config_id}


@router.post("/configs/{config_id}/test", response_model=LLMTestResponse)
async def test_config(
    config_id: str,
    payload: LLMTestRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("super_admin")),
):
    cfg = await db.get(LLMConfig, config_id)
    if not cfg:
        raise HTTPException(status_code=404, detail="配置不存在")

    from app.services.llm.factory import _build_client
    from app.core.security import decrypt_api_key
    try:
        client = _build_client(cfg, decrypt_api_key(cfg.api_key_encrypted))
        t0 = time.monotonic()
        result = await client.test_basic()
        latency = (time.monotonic() - t0) * 1000
        return LLMTestResponse(success=True, latency_ms=round(latency, 1), result=result)
    except Exception as e:
        return LLMTestResponse(success=False, latency_ms=0.0, error=str(e))
