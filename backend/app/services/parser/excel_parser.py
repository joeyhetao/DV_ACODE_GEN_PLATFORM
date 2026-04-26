from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import openpyxl

from app.services.registry import get_registry

def _col_to_idx(col_letter: str) -> int:
    result = 0
    for ch in col_letter.upper():
        result = result * 26 + (ord(ch) - ord("A") + 1)
    return result


@dataclass
class SignalInfo:
    name: str
    width: int
    role: str


@dataclass
class ParsedRow:
    row_id: str
    code_type: str
    module: str
    clk: str
    rst: str
    rst_polarity: str
    protocol: str | None
    intent: str
    signals: list[SignalInfo] = field(default_factory=list)
    extra: dict = field(default_factory=dict)


def parse_excel(file_path: Path, code_type: str) -> list[ParsedRow]:
    registry = get_registry()
    schema = registry.get_excel_schema(code_type)
    ct_def = registry.get(code_type)

    wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)

    sheet_name = ct_def.excel_sheet_name
    if sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
    else:
        ws = wb.active

    rows = list(ws.iter_rows(min_row=2, values_only=True))
    wb.close()

    fields_def = {f["col"]: f for f in schema["fields"] if not f.get("output")}
    signals_def = schema.get("signals")

    results: list[ParsedRow] = []
    for raw_row in rows:
        if not raw_row or not raw_row[0]:
            continue

        def get_cell(col_letter: str):
            idx = _col_to_idx(col_letter) - 1
            if idx < len(raw_row):
                v = raw_row[idx]
                return str(v).strip() if v is not None else None
            return None

        extra: dict = {}
        for col, fdef in fields_def.items():
            val = get_cell(col)
            extra[fdef["field_key"]] = val

        signals: list[SignalInfo] = []
        if signals_def:
            start_col = signals_def["start_col"]
            max_count = signals_def["max_count"]
            cpp = signals_def["cols_per_signal"]
            start_idx = _col_to_idx(start_col)

            for i in range(max_count):
                base = start_idx + i * cpp - 1
                if base >= len(raw_row):
                    break
                name = str(raw_row[base]).strip() if raw_row[base] else None
                if not name:
                    continue
                width_raw = raw_row[base + 1] if base + 1 < len(raw_row) else None
                role_raw = raw_row[base + 2] if base + 2 < len(raw_row) else None
                try:
                    width = int(width_raw) if width_raw else 1
                except (ValueError, TypeError):
                    width = 1
                role = str(role_raw).strip() if role_raw else "other"
                signals.append(SignalInfo(name=name, width=width, role=role))

        row = ParsedRow(
            row_id=extra.get("row_id", ""),
            code_type=code_type,
            module=extra.get("module", ""),
            clk=extra.get("clk", "clk"),
            rst=extra.get("rst", "rst_n"),
            rst_polarity=extra.get("rst_polarity", "低有效"),
            protocol=extra.get("protocol"),
            intent=extra.get("intent", ""),
            signals=signals,
            extra=extra,
        )
        results.append(row)

    return results
