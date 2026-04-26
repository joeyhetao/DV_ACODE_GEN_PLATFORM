from __future__ import annotations
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import get_settings
from app.core.vector_store import get_qdrant
from app.services.embedding_client import get_embedding_client


async def check_name_duplicate(db: AsyncSession, name: str, exclude_id: str | None = None) -> bool:
    from app.models.template import Template

    stmt = select(Template).where(Template.name == name)
    if exclude_id:
        stmt = stmt.where(Template.id != exclude_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none() is not None


async def check_semantic_duplicate(
    description: str,
    name: str,
    tags: list[str] | None = None,
    keywords: list[str] | None = None,
    top_k: int = 3,
) -> list[dict]:
    settings = get_settings()
    qdrant = get_qdrant()
    embed_client = get_embedding_client()

    encode_text = f"{name}。{description}。"
    if tags:
        encode_text += f"标签：{' '.join(tags)}。"
    if keywords:
        encode_text += f"关键词：{' '.join(keywords)}。"

    dense_vecs = await embed_client.embed_dense([encode_text])
    dense_vec = dense_vecs[0]

    results = await qdrant.search(
        collection_name=settings.qdrant_collection,
        query_vector=("dense", dense_vec),
        limit=top_k,
        score_threshold=settings.template_dedup_threshold,
        with_payload=True,
    )

    return [
        {
            "template_id": r.payload.get("template_id"),
            "score": round(r.score, 4),
        }
        for r in results
    ]
