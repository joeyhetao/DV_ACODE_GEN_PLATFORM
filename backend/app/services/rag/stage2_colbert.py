from __future__ import annotations
import numpy as np
from app.core.config import get_settings


def colbert_max_sim(query_colbert: list[list[float]], doc_colbert: list[list[float]]) -> float:
    q = np.array(query_colbert, dtype=np.float32)
    d = np.array(doc_colbert, dtype=np.float32)
    sim_matrix = q @ d.T
    max_sim_per_token = sim_matrix.max(axis=-1)
    return float(max_sim_per_token.mean())


def stage2_colbert_rerank(
    query_colbert: list[list[float]],
    stage1_results: list[dict],
    top_k: int | None = None,
) -> list[dict]:
    settings = get_settings()
    limit = top_k or settings.rag_stage2_top_k

    scored: list[tuple[float, dict]] = []
    for item in stage1_results:
        doc_colbert = item.get("colbert_vec")
        if not doc_colbert:
            scored.append((item["score"], item))
            continue
        score = colbert_max_sim(query_colbert, doc_colbert)
        scored.append((score, {**item, "score": score}))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in scored[:limit]]
