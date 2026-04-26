from fastapi import FastAPI
from app.routers import embed, rerank
from app.models import get_embed_model, get_rerank_model

app = FastAPI(title="Embedding Service", version="1.0.0")

app.include_router(embed.router)
app.include_router(rerank.router)


@app.on_event("startup")
def _preload_models() -> None:
    get_embed_model()
    get_rerank_model()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
