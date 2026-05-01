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
                "dense": VectorParams(size=1024, distance=Distance.COSINE),
            },
            sparse_vectors_config={
                "sparse": SparseVectorParams(index=SparseIndexParams()),
            },
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
