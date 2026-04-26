from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.models.user import User
from app.schemas.intent import IntentBuildRequest, IntentBuildResponse, ScenariosResponse, Scenario, ScenarioParam
from app.services.intent.builder import build_intent, get_all_scenarios

router = APIRouter(prefix="/intent-builder", tags=["intent-builder"])


@router.get("/scenarios", response_model=ScenariosResponse)
async def list_scenarios(
    code_type: str = "assertion",
    current_user: User = Depends(get_current_user),
):
    raw = get_all_scenarios(code_type)
    scenarios = []
    for s in raw:
        param_names = [p for p in s.get("params", [])]
        scenarios.append(Scenario(
            id=s["id"],
            name=s.get("name", s["id"]),
            description=s.get("description", ""),
            params=[ScenarioParam(name=p, description=p) for p in param_names],
            template=s.get("template", ""),
        ))
    return ScenariosResponse(code_type=code_type, scenarios=scenarios)


@router.post("/build", response_model=IntentBuildResponse)
async def build(
    payload: IntentBuildRequest,
    current_user: User = Depends(get_current_user),
):
    try:
        intent_text = build_intent(
            code_type=payload.code_type,
            scenario_id=payload.scenario_type,
            params=payload.params,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return IntentBuildResponse(intent_text=intent_text)
