from __future__ import annotations
import httpx
from app.core.config import get_settings


class EmbeddingClient:
    def __init__(self) -> None:
        settings = get_settings()
        self._base_url = settings.embedding_service_url
        self._client = httpx.AsyncClient(timeout=60.0)

    async def embed(
        self,
        texts: list[str],
        modes: list[str] | None = None,
    ) -> dict:
        if modes is None:
            modes = ["dense", "sparse", "colbert"]
        resp = await self._client.post(
            f"{self._base_url}/embed",
            json={"texts": texts, "modes": modes},
        )
        resp.raise_for_status()
        return resp.json()

    async def embed_dense(self, texts: list[str]) -> list[list[float]]:
        result = await self.embed(texts, modes=["dense"])
        return result["dense"]

    async def rerank(self, query: str, candidates: list[str]) -> list[float]:
        resp = await self._client.post(
            f"{self._base_url}/rerank",
            json={"query": query, "candidates": candidates},
        )
        resp.raise_for_status()
        return resp.json()["scores"]

    async def close(self) -> None:
        await self._client.aclose()


_client: EmbeddingClient | None = None


def get_embedding_client() -> EmbeddingClient:
    global _client
    if _client is None:
        _client = EmbeddingClient()
    return _client
