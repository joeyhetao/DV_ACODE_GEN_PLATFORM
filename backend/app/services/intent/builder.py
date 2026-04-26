from __future__ import annotations
from app.services.registry import get_registry


def build_intent(code_type: str, scenario_id: str, params: dict[str, str]) -> str:
    registry = get_registry()
    scenarios = registry.get_scenarios(code_type)

    scenario = next((s for s in scenarios if s["id"] == scenario_id), None)
    if scenario is None:
        raise ValueError(f"场景 {scenario_id} 在类型 {code_type} 中不存在")

    template = scenario["template"]
    try:
        return template.format(**params)
    except KeyError as e:
        raise ValueError(f"缺少参数: {e}") from e


def get_all_scenarios(code_type: str) -> list[dict]:
    return get_registry().get_scenarios(code_type)
