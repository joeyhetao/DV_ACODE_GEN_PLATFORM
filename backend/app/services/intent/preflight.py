from __future__ import annotations
from app.core.config import get_settings
from app.core.vector_store import get_qdrant
from app.services.embedding_client import get_embedding_client
from qdrant_client.models import SparseVector, NamedSparseVector, Prefetch, FusionQuery, Fusion


async def preflight_row(row_id: str, intent_text: str) -> dict:
    settings = get_settings()
    qdrant = get_qdrant()
    embed_client = get_embedding_client()

    embed_result = await embed_client.embed([intent_text], modes=["dense", "sparse"])
    dense_vec = embed_result["dense"][0]
    sparse_raw = embed_result["sparse"][0]

    sparse_vector = SparseVector(
        indices=[int(k) for k in sparse_raw.keys()],
        values=list(sparse_raw.values()),
    )

    results = await qdrant.query_points(
        collection_name=settings.qdrant_collection,
        prefetch=[
            Prefetch(query=dense_vec, using="dense", limit=3),
            Prefetch(
                query=NamedSparseVector(name="sparse", vector=sparse_vector),
                using="sparse",
                limit=3,
            ),
        ],
        query=FusionQuery(fusion=Fusion.RRF),
        limit=3,
        with_payload=True,
    )

    if not results.points:
        return {"row_id": row_id, "estimated_confidence": 0.0, "top_match": None}

    top = results.points[0]
    top_match = None
    if top.score >= settings.confidence_threshold:
        top_match = {
            "template_id": top.payload.get("template_id"),
            "name": top.payload.get("name", ""),
        }

    return {
        "row_id": row_id,
        "estimated_confidence": round(top.score, 4),
        "top_match": top_match,
    }
