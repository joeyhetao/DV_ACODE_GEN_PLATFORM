from __future__ import annotations
import os
import torch
from FlagEmbedding import BGEM3FlagModel, FlagReranker

_embed_model: BGEM3FlagModel | None = None
_rerank_model: FlagReranker | None = None


def get_embed_model() -> BGEM3FlagModel:
    global _embed_model
    if _embed_model is None:
        model_name = os.getenv("EMBED_MODEL", "BAAI/bge-m3")
        device = os.getenv("DEVICE", "cuda" if torch.cuda.is_available() else "cpu")
        _embed_model = BGEM3FlagModel(
            model_name,
            use_fp16=(device == "cuda"),
            device=device,
        )
    return _embed_model


def get_rerank_model() -> FlagReranker:
    global _rerank_model
    if _rerank_model is None:
        model_name = os.getenv("RERANK_MODEL", "BAAI/bge-reranker-v2-m3")
        device = os.getenv("DEVICE", "cuda" if torch.cuda.is_available() else "cpu")
        _rerank_model = FlagReranker(
            model_name,
            use_fp16=(device == "cuda"),
            device=device,
        )
    return _rerank_model
