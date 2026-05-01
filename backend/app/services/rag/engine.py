from __future__ import annotations
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import get_settings
from app.services.embedding_client import get_embedding_client
from app.services.rag.stage1_hybrid import stage1_hybrid_search
from app.services.rag.stage2_colbert import stage2_colbert_rerank
from app.services.rag.stage3_reranker import stage3_rerank


async def rag_retrieve(
    normalized_intent: str,
    db: AsyncSession,
    code_type: str | None = None,
) -> list[dict]:
    from app.models.template import Template

    settings = get_settings()
    embed_client = get_embedding_client()

    embed_result = await embed_client.embed(
        [normalized_intent],
        modes=["dense", "sparse", "colbert"],
    )
    dense_vec = embed_result["dense"][0]
    sparse_vec = embed_result["sparse"][0]
    colbert_vec = embed_result["colbert"][0]

    stage1 = await stage1_hybrid_search(
        dense_vec=dense_vec,
        sparse_vec=sparse_vec,
        top_k=settings.rag_stage1_top_k,
        code_type=code_type,
    )

    stage2 = stage2_colbert_rerank(
        query_colbert=colbert_vec,
        stage1_results=stage1,
        top_k=settings.rag_stage2_top_k,
    )

    template_ids = [r["template_id"] for r in stage2 if r["template_id"]]
    if not template_ids:
        return []

    stmt = select(Template).where(
        Template.id.in_(template_ids),
        Template.is_active == True,
    )
    result = await db.execute(stmt)
    templates_by_id = {t.id: t for t in result.scalars().all()}

    candidate_texts = []
    valid_stage2 = []
    for item in stage2:
        tmpl = templates_by_id.get(item["template_id"])
        if tmpl:
            parts = [tmpl.name, tmpl.description]
            if tmpl.keywords:
                parts.append(" ".join(tmpl.keywords))
            candidate_texts.append("。".join(parts))
            valid_stage2.append(item)

    try:
        stage3 = await stage3_rerank(
            query_text=normalized_intent,
            stage2_results=valid_stage2,
            candidate_texts=candidate_texts,
            top_k=settings.rag_stage3_top_k,
        )
    except Exception:
        stage3 = valid_stage2[: settings.rag_stage3_top_k]

    enriched = []
    for item in stage3:
        tmpl = templates_by_id.get(item["template_id"])
        if tmpl:
            enriched.append({
                "template_id": tmpl.id,
                "name": tmpl.name,
                "description": tmpl.description,
                "score": item["score"],
                "template": tmpl,
            })

    return enriched
