from __future__ import annotations
import numpy as np
from app.core.config import get_settings


# FEAT-13 maturity 门控说明：
# stage2 不需要单独的 maturity Filter。stage1 hybrid 搜索的 Qdrant Filter 已经
# 把候选限定在 maturity_level='production' 子集，stage2 只是对 stage1 输出做 ColBERT
# late-interaction 重排，输入侧已纯净。
#
# 实际上 stage2 当前是 bypass 的（embedding_service 不返回 colbert_vec，
# colbert_vec 永远为 None，stage2 透传 stage1 RRF 分数）——见 CLAUDE.md
# Architecture 章节。未来若重启 ColBERT（补 collection 多向量 schema + reindex），
# 也无需在此处独立加 maturity Filter，stage1 已是单一来源。


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
