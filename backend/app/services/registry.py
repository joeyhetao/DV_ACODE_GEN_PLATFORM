from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import yaml

_DATA_DIR = Path(__file__).parent.parent.parent / "data"


@dataclass
class CodeTypeDefinition:
    id: str
    display_name: str
    excel_sheet_name: str
    excel_schema_file: str
    signal_roles: list[str]
    normalization_pattern: str
    scenario_templates_file: str
    subcategories: list[str]


class CodeTypeRegistry:
    def __init__(self) -> None:
        self._types: dict[str, CodeTypeDefinition] = {}
        self._load()

    def _load(self) -> None:
        code_types_dir = _DATA_DIR / "code_types"
        for yaml_path in sorted(code_types_dir.glob("*.yaml")):
            raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
            ct = CodeTypeDefinition(
                id=raw["id"],
                display_name=raw["display_name"],
                excel_sheet_name=raw["excel_sheet_name"],
                excel_schema_file=raw["excel_schema_file"],
                signal_roles=raw.get("signal_roles", []),
                normalization_pattern=raw["normalization_pattern"],
                scenario_templates_file=raw["scenario_templates_file"],
                subcategories=raw.get("subcategories", []),
            )
            self._types[ct.id] = ct

    def get(self, code_type_id: str) -> CodeTypeDefinition:
        if code_type_id not in self._types:
            raise ValueError(f"未知代码类型: {code_type_id}")
        return self._types[code_type_id]

    def all(self) -> list[CodeTypeDefinition]:
        return list(self._types.values())

    def ids(self) -> list[str]:
        return list(self._types.keys())

    def get_normalization_pattern(self, code_type_id: str) -> str:
        return self.get(code_type_id).normalization_pattern

    def get_excel_schema(self, code_type_id: str) -> dict:
        ct = self.get(code_type_id)
        schema_path = _DATA_DIR / ct.excel_schema_file
        return yaml.safe_load(schema_path.read_text(encoding="utf-8"))

    def get_scenarios(self, code_type_id: str) -> list[dict]:
        ct = self.get(code_type_id)
        scenarios_path = _DATA_DIR / ct.scenario_templates_file
        raw = yaml.safe_load(scenarios_path.read_text(encoding="utf-8"))
        return raw.get("scenarios", [])

    def build_normalization_rules(self) -> str:
        lines = []
        for i, ct in enumerate(self._types.values(), start=1):
            lines.append(
                f"{i}. {ct.display_name}意图（code_type={ct.id}）→ 格式：\"{ct.normalization_pattern}\""
            )
        n = len(lines) + 1
        lines.append(f"{n}. 只改表达方式，不改变语义")
        lines.append(f"{n + 1}. 如果无法判断类型，输出原文")
        lines.append(f"{n + 2}. 输出一句话，不加任何解释")
        return "\n".join(lines)


_registry: CodeTypeRegistry | None = None


def get_registry() -> CodeTypeRegistry:
    global _registry
    if _registry is None:
        _registry = CodeTypeRegistry()
    return _registry
