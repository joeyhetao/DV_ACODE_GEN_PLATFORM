from __future__ import annotations
from pydantic import BaseModel


class TemplateSelectionOutput(BaseModel):
    template_id: str
    param_mapping: dict[str, str]
    confidence: float


class ScenarioParam(BaseModel):
    name: str
    description: str
    required: bool = True


class Scenario(BaseModel):
    id: str
    name: str
    description: str
    params: list[ScenarioParam]
    template: str


class ScenariosResponse(BaseModel):
    code_type: str
    scenarios: list[Scenario]


class IntentBuildRequest(BaseModel):
    code_type: str
    scenario_type: str
    params: dict[str, str]


class IntentBuildResponse(BaseModel):
    intent_text: str
