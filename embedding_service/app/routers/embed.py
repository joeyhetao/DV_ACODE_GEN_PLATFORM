from fastapi import APIRouter
from app.schemas import EmbedRequest, EmbedResponse
from app.models import get_embed_model

router = APIRouter()


@router.post("/embed", response_model=EmbedResponse)
def embed(req: EmbedRequest) -> EmbedResponse:
    model = get_embed_model()
    want_dense = "dense" in req.modes
    want_sparse = "sparse" in req.modes
    want_colbert = "colbert" in req.modes

    output = model.encode(
        req.texts,
        return_dense=want_dense,
        return_sparse=want_sparse,
        return_colbert_vecs=want_colbert,
        batch_size=12,
    )

    resp = EmbedResponse()
    if want_dense:
        resp.dense = output["dense_vecs"].tolist()
    if want_sparse:
        # FlagEmbedding returns list of {token_id: weight} dicts
        resp.sparse = [
            {str(k): float(v) for k, v in s.items()}
            for s in output["lexical_weights"]
        ]
    if want_colbert:
        resp.colbert = [cv.tolist() for cv in output["colbert_vecs"]]

    return resp
