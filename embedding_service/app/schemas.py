from __future__ import annotations
from typing import Literal
from pydantic import BaseModel


class EmbedRequest(BaseModel):
    texts: list[str]
    modes: list[Literal["dense", "sparse", "colbert"]] = ["dense", "sparse", "colbert"]


class EmbedResponse(BaseModel):
    dense: list[list[float]] | None = None
    sparse: list[dict[str, float]] | None = None
    colbert: list[list[list[float]]] | None = None


class RerankRequest(BaseModel):
    query: str
    candidates: list[str]


class RerankResponse(BaseModel):
    scores: list[float]
