from __future__ import annotations
from app.core.config import get_settings
from app.services.embedding_client import get_embedding_client


async def stage3_rerank(
    query_text: str,
    stage2_results: list[dict],
    candidate_texts: list[str],
    top_k: int | None = None,
) -> list[dict]:
    settings = get_settings()
    limit = top_k or settings.rag_stage3_top_k

    if not stage2_results:
        return []

    embed_client = get_embedding_client()
    scores = await embed_client.rerank(query_text, candidate_texts)

    reranked = [
        {**item, "score": round(float(scores[i]), 4)}
        for i, item in enumerate(stage2_results)
        if i < len(scores)
    ]
    reranked.sort(key=lambda x: x["score"], reverse=True)
    return reranked[:limit]
