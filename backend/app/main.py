# FastAPI application entrypoint: builds the app, initializes Qdrant collections, and mounts API routers.
from __future__ import annotations
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import engine, AsyncSessionLocal
from app.api.v1.router import v1_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await _init_db()
    await _ensure_super_admin()
    await _init_qdrant_collection()
    yield
    await engine.dispose()


async def _init_db():
    import app.models  # noqa: F401 — ensures all models are registered with Base.metadata
    from app.core.database import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def _ensure_super_admin():
    from app.models.user import User
    from app.core.security import hash_password
    settings = get_settings()

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(User).where(User.username == settings.super_admin_username)
        )
        if result.scalar_one_or_none() is None:
            admin = User(
                username=settings.super_admin_username,
                email=settings.super_admin_email,
                hashed_password=hash_password(settings.super_admin_password),
                role="super_admin",
                is_active=True,
            )
            db.add(admin)
            await db.commit()


async def _init_qdrant_collection():
    from qdrant_client.models import Distance, VectorParams, SparseVectorParams, SparseIndexParams
    from app.core.config import get_settings
    from app.core.vector_store import get_qdrant

    settings = get_settings()
    qdrant = get_qdrant()

    collections = await qdrant.get_collections()
    existing = [c.name for c in collections.collections]

    if settings.qdrant_collection not in existing:
        await qdrant.create_collection(
            collection_name=settings.qdrant_collection,
            vectors_config={
                "dense": VectorParams(size=settings.embedding_dim, distance=Distance.COSINE),
            },
            sparse_vectors_config={
                "sparse": SparseVectorParams(index=SparseIndexParams()),
            },
        )
    else:
        # collection 已存在：检查 dense 维度与当前配置一致，避免 embed_dim 改了
        # 但 Qdrant 端没 reindex 导致 upsert 时 dimension mismatch 静默失败。
        info = await qdrant.get_collection(settings.qdrant_collection)
        actual_dim = None
        params = getattr(info.config, "params", None)
        vectors = getattr(params, "vectors", None) if params else None
        if vectors and isinstance(vectors, dict):
            dense_cfg = vectors.get("dense")
            actual_dim = getattr(dense_cfg, "size", None) if dense_cfg else None
        if actual_dim is not None and actual_dim != settings.embedding_dim:
            print(
                f"[WARN] Qdrant collection {settings.qdrant_collection!r} dense dim={actual_dim} "
                f"!= settings.embedding_dim={settings.embedding_dim}. "
                f"换 embedding 模型后必须 `lib_manager.py rebuild` 重建 collection。",
                flush=True,
            )


settings = get_settings()

app = FastAPI(
    title="DV ACODE GEN PLATFORM",
    version="1.0.0",
    description="IC验证辅助代码生成平台 API",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(v1_router)


@app.get("/health")
@app.get("/api/health")
async def health():
    return {"status": "ok"}
