from __future__ import annotations
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from qdrant_client.models import Filter, FieldCondition, MatchValue

from app.core.config import get_settings
from app.core.vector_store import get_qdrant
from app.services.embedding_client import get_embedding_client
from app.services.rag.stage1_hybrid import stage1_hybrid_search
from app.services.rag.stage2_colbert import stage2_colbert_rerank
from app.services.rag.stage3_reranker import stage3_rerank


async def dense_top1_score(query_text: str, code_type: str | None = None) -> float:
    """专为 off-topic 阈值闸用：单独发一次 dense-only Qdrant 查询，取 top1 余弦分数。

    返回的是 bge-m3 dense L2 归一化点积（绝对相似度），跨语料稳定，可固定阈值。
    与 stage1_hybrid 的 RRF 融合分数不同——RRF 是 rank 融合产物，不可校准。

    FEAT-13：仅在 maturity_level='production' 子集上打分。代码类型 mismatch gate
    也会调到这里，自动生效。注意 off-topic 阈值原先基于全量语料校准，过滤后分布若有
    显著差异需重跑 calibrate_offtopic_threshold.py。
    """
    embed_client = get_embedding_client()
    qdrant = get_qdrant()
    settings = get_settings()

    embed_result = await embed_client.embed([query_text], modes=["dense"])
    dense_vec = embed_result["dense"][0]

    must_conditions: list[FieldCondition] = [
        FieldCondition(key="maturity_level", match=MatchValue(value="production"))
    ]
    if code_type:
        must_conditions.append(
            FieldCondition(key="code_type", match=MatchValue(value=code_type))
        )
    query_filter = Filter(must=must_conditions)

    res = await qdrant.query_points(
        collection_name=settings.qdrant_collection,
        query=dense_vec,
        using="dense",
        limit=1,
        query_filter=query_filter,
    )
    return float(res.points[0].score) if res.points else 0.0


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
        maturity_level="production",
    )

    stage2 = stage2_colbert_rerank(
        query_colbert=colbert_vec,
        stage1_results=stage1,
        top_k=settings.rag_stage2_top_k,
    )

    template_ids = [r["template_id"] for r in stage2 if r["template_id"]]
    if not template_ids:
        return []

    # FEAT-13 双重防御：stage1 Qdrant Filter 已按 maturity_level='production' 过滤；
    # 此处 DB 层再加一道，即便 Qdrant payload 因冷启动 / 漂移漏入了非 production 模板，
    # 也能在 DB 层兜底拦截。
    stmt = select(Template).where(
        Template.id.in_(template_ids),
        Template.is_active == True,
        Template.maturity_level == "production",
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
