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
        # 单文件失败不影响整体启动：YAML 损坏 / 必填字段缺失 → 跳过该文件并打日志，
        # 已加载的 code_types 仍生效。避免一处手抖整个 backend 起不来。
        for yaml_path in sorted(code_types_dir.glob("*.yaml")):
            try:
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
            except (yaml.YAMLError, KeyError, TypeError) as e:
                print(
                    f"[WARN] registry: skipping {yaml_path.name} due to {type(e).__name__}: {e}",
                    flush=True,
                )

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
        # v3.0 契约：normalize_intent 仅做同义改写以稳定 cache key，不做"猜你想说什么"
        # 的扩写。anti-fill 约束（最后 3 条）明文禁止填空 / 推断 / 扩写——若描述里没说，
        # 保持原文写法不要补；后续 under_specified 闸自然会捕获参数空缺。
        lines = []
        for i, ct in enumerate(self._types.values(), start=1):
            lines.append(
                f"{i}. {ct.display_name}意图（code_type={ct.id}）→ 格式：\"{ct.normalization_pattern}\""
            )
        n = len(lines) + 1
        lines.append(f"{n}. 只改表达方式，不改变语义")
        lines.append(f"{n + 1}. 如果无法判断类型，输出原文")
        lines.append(f"{n + 2}. 输出一句话，不加任何解释")
        n += 3
        # v3.0 anti-fill 约束
        lines.append(f"{n}. 【禁止】不允许填空——如果用户没提到信号名 / 状态列表 / 位宽等参数值，不要替他写出来")
        lines.append(f"{n + 1}. 【禁止】不允许扩写或推断——不要按「AXI 协议常见信号」之类的领域知识替用户编造未提及的内容")
        lines.append(f"{n + 2}. 【禁止】不允许凭空命名——任何在原文中未出现的具体信号名 / 状态名都不应在输出里出现")
        return "\n".join(lines)


_registry: CodeTypeRegistry | None = None


def get_registry() -> CodeTypeRegistry:
    global _registry
    if _registry is None:
        _registry = CodeTypeRegistry()
    return _registry
