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
from app.schemas.template import MaturityLevel


async def stage1_hybrid_search(
    dense_vec: list[float],
    sparse_vec: dict[str, float],
    top_k: int | None = None,
    code_type: str | None = None,
    maturity_level: MaturityLevel = "production",
) -> list[dict]:
    settings = get_settings()
    qdrant = get_qdrant()
    limit = top_k or settings.rag_stage1_top_k

    sparse_vector = SparseVector(
        indices=[int(k) for k in sparse_vec.keys()],
        values=list(sparse_vec.values()),
    )

    # FEAT-13 maturity 门控：默认仅召回 production 模板。Qdrant payload 中
    # 没有 maturity_level 字段的旧 point 会被过滤掉——上线前必须 lib_manager
    # rebuild 让所有 point payload 带上 maturity_level。
    must_conditions: list[FieldCondition] = []
    if code_type:
        must_conditions.append(
            FieldCondition(key="code_type", match=MatchValue(value=code_type))
        )
    if maturity_level:
        must_conditions.append(
            FieldCondition(key="maturity_level", match=MatchValue(value=maturity_level))
        )
    query_filter = Filter(must=must_conditions) if must_conditions else None

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
