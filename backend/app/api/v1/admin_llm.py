from __future__ import annotations
import time
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.security import require_role
from app.core.security import encrypt_api_key, mask_api_key
from app.models.user import User
from app.models.llm_config import LLMConfig
from app.schemas.llm_config import LLMConfigCreate, LLMConfigUpdate, LLMConfigOut, LLMTestRequest, LLMTestResponse

router = APIRouter(prefix="/admin/llm", tags=["admin-llm"])


def _to_config_out(c: LLMConfig) -> LLMConfigOut:
    return LLMConfigOut(
        id=c.id, name=c.name, provider=c.provider, base_url=c.base_url,
        api_key_masked=mask_api_key(c.api_key_encrypted or ""),
        model_id=c.model_id, output_mode=c.output_mode,
        temperature=c.temperature, max_tokens=c.max_tokens,
        is_active=c.is_active, is_default=c.is_default,
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
    )
    if payload.is_default:
        await db.execute(
            LLMConfig.__table__.update().where(LLMConfig.is_default == True).values(is_default=False)
        )
    db.add(cfg)
    await db.commit()
    await db.refresh(cfg)
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

    data = payload.model_dump(exclude_none=True)
    if "api_key" in data:
        cfg.api_key_encrypted = encrypt_api_key(data.pop("api_key"))

    if data.get("is_default"):
        await db.execute(
            LLMConfig.__table__.update().where(LLMConfig.id != config_id).values(is_default=False)
        )

    for field, value in data.items():
        setattr(cfg, field, value)

    await db.commit()
    await db.refresh(cfg)
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
    await db.delete(cfg)
    await db.commit()


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
