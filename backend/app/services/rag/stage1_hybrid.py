from __future__ import annotations
from qdrant_client.models import (
    Prefetch,
    FusionQuery,
    Fusion,
    SparseVector,
    Filter,
    FieldCondition,
    MatchValue,
)
from app.core.config import get_settings
from app.core.vector_store import get_qdrant


async def stage1_hybrid_search(
    dense_vec: list[float],
    sparse_vec: dict[str, float],
    top_k: int | None = None,
    code_type: str | None = None,
) -> list[dict]:
    settings = get_settings()
    qdrant = get_qdrant()
    limit = top_k or settings.rag_stage1_top_k

    sparse_vector = SparseVector(
        indices=[int(k) for k in sparse_vec.keys()],
        values=list(sparse_vec.values()),
    )

    query_filter = None
    if code_type:
        query_filter = Filter(
            must=[FieldCondition(key="code_type", match=MatchValue(value=code_type))]
        )

    results = await qdrant.query_points(
        collection_name=settings.qdrant_collection,
        prefetch=[
            Prefetch(
                query=dense_vec,
                using="dense",
                limit=limit,
                filter=query_filter,
            ),
            Prefetch(
                query=sparse_vector,
                using="sparse",
                limit=limit,
                filter=query_filter,
            ),
        ],
        query=FusionQuery(fusion=Fusion.RRF),
        limit=limit,
        with_payload=True,
    )

    return [
        {
            "qdrant_id": str(r.id),
            "template_id": r.payload.get("template_id"),
            "score": r.score,
            "colbert_vec": r.vector.get("colbert") if r.vector else None,
            "payload": r.payload,
        }
        for r in results.points
    ]
