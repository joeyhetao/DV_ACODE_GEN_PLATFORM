from fastapi import APIRouter
from app.schemas import RerankRequest, RerankResponse
from app.models import get_rerank_model

router = APIRouter()


@router.post("/rerank", response_model=RerankResponse)
def rerank(req: RerankRequest) -> RerankResponse:
    model = get_rerank_model()
    pairs = [[req.query, cand] for cand in req.candidates]
    scores = model.compute_score(pairs, normalize=True)
    if isinstance(scores, float):
        scores = [scores]
    return RerankResponse(scores=[float(s) for s in scores])
