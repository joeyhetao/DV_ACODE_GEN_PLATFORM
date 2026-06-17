"""FEAT-18 — 批量页 sheet 自动检测多 code_type 解析路径单测。

覆盖 spec §2 / §3 全部 AC：

- `test_multisheet_only_assertion_sheet_filled` — 仅 SVA 需求 sheet 有数据行 →
  `parse_excel_multisheet` 返回行的 code_type 全为 "assertion"，行为与单 sheet
  路径等同。
- `test_multisheet_both_sheets_filled` — SVA + Coverage 两 sheet 均有数据 →
  返回行混合 "assertion" + "coverage" 两类（顺序按 registry.all() 排）。
- `test_multisheet_all_empty_raises_no_valid_rows` — 两个 sheet 均为空 →
  `parse_excel_multisheet` 抛 `ValueError("no_valid_rows")`，`POST /batch/upload`
  和 `POST /batch/preflight` 转 HTTP 400 + `detail.type == "no_valid_rows"`。
- `test_multisheet_unknown_sheet_silently_skipped` — workbook 含已知 SVA sheet
  + 未知 "Garbage" sheet（手工写入数据），multisheet 应只返回 SVA 行，Garbage
  sheet 静默跳过。
- `test_gate2_batch_reason_contains_sheet_keyword` — `_build_code_type_mismatch_reason`
  helper 输出文案含 "sheet" 关键词 + selected sheet 名 + suggested code_type，
  验证批量场景文案覆盖生效。

跑法：
    docker compose exec backend pytest tests/test_batch_multisheet_parse.py -v

测试不依赖 live PG / Redis / LLM / Qdrant：parse_excel_multisheet 是纯 I/O；
gate 2 helper 调 get_registry() 走静态 YAML；端点测试 mock 掉 DB 与
preflight_row（preflight_row 在 0 数据行时不会被调用，no_valid_rows case
也走不到那里）。
"""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock

import openpyxl
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.batch import router as batch_router
from app.core.security import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.services.parser.excel_parser import parse_excel_multisheet
from app.services.parser.template_writer import build_template_workbook
from app.services.registry import get_registry
from app.tasks.batch_tasks import _build_code_type_mismatch_reason


# ── helpers ─────────────────────────────────────────────────────────────

def _make_user() -> User:
    u = MagicMock(spec=User)
    u.id = "user-1"
    u.role = "user"
    return u


def _build_authed_app() -> FastAPI:
    """挂 batch router 的最小 FastAPI app + override get_current_user / get_db。
    avoid main.py lifespan 里的 DB / Qdrant 初始化。"""
    app = FastAPI()
    app.include_router(batch_router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: _make_user()
    # /preflight 不依赖 DB（不写 BatchJob），用一个 MagicMock 即可；但 FastAPI
    # 依赖解析仍会调用 get_db，所以 override 为 no-op async gen 兜底。
    async def _noop_db():
        yield MagicMock()
    app.dependency_overrides[get_db] = _noop_db
    return app


def _make_sva_workbook(file_path: Path, *, row_ids: list[str]) -> None:
    """生成 SVA 需求 sheet 含 row_ids 列数据行的 workbook + 空 Coverage 需求 sheet。

    用 build_template_workbook 取真实 sheet 名 + 表头，再在 SVA 需求 sheet 的
    row 2 起按 row_id 数填入数据（A 列 row_id、B 列 module、C 列 clk、D 列 rst、
    E 列 rst_polarity、S 列 intent）。这样既保证表头列结构对齐 schema，又能
    生成可被 parse_excel_multisheet 识别的真实数据行。
    """
    wb = build_template_workbook(get_registry())
    ws = wb["SVA需求"]
    # 占位说明在 row 2（B2），数据从 row 3 起
    for i, rid in enumerate(row_ids, start=3):
        ws.cell(row=i, column=1, value=rid)  # A: row_id
        ws.cell(row=i, column=2, value="cpu")  # B: module
        ws.cell(row=i, column=3, value="clk")  # C: clk
        ws.cell(row=i, column=4, value="rst_n")  # D: rst
        ws.cell(row=i, column=5, value="低有效")  # E: rst_polarity
        ws.cell(row=i, column=19, value=f"intent for {rid}")  # S (19): intent
    wb.save(file_path)


def _make_dual_workbook(
    file_path: Path, *, sva_row_ids: list[str], cov_row_ids: list[str]
) -> None:
    """两 sheet 都填数据：SVA 需求 + Coverage 需求。"""
    wb = build_template_workbook(get_registry())
    ws_sva = wb["SVA需求"]
    for i, rid in enumerate(sva_row_ids, start=3):
        ws_sva.cell(row=i, column=1, value=rid)
        ws_sva.cell(row=i, column=2, value="cpu")
        ws_sva.cell(row=i, column=19, value=f"sva intent for {rid}")

    ws_cov = wb["Coverage需求"]
    # Coverage schema intent 在 R 列（idx 18）；main_signal_name 在 G(7) / width H(8) /
    # dtype I(9)。填最低限度让 ParsedRow 非空（A 列编号即可触发 row 入列）。
    for i, rid in enumerate(cov_row_ids, start=3):
        ws_cov.cell(row=i, column=1, value=rid)
        ws_cov.cell(row=i, column=2, value="cpu")
        ws_cov.cell(row=i, column=18, value=f"cov intent for {rid}")
    wb.save(file_path)


def _make_unknown_sheet_workbook(file_path: Path, *, sva_row_ids: list[str]) -> None:
    """SVA 需求 + 一个 "Garbage" 未知 sheet（含 A 列数据）；multisheet 应只识 SVA。"""
    wb = build_template_workbook(get_registry())
    ws_sva = wb["SVA需求"]
    for i, rid in enumerate(sva_row_ids, start=3):
        ws_sva.cell(row=i, column=1, value=rid)
        ws_sva.cell(row=i, column=2, value="cpu")
        ws_sva.cell(row=i, column=19, value=f"sva intent for {rid}")

    garbage = wb.create_sheet(title="Garbage")
    garbage.cell(row=1, column=1, value="编号")
    garbage.cell(row=2, column=1, value="GARBAGE-1")
    garbage.cell(row=2, column=2, value="should be ignored")
    wb.save(file_path)


# ── 1. 仅一个 sheet 有数据：行为与单 code_type 路径等同 ──────────────────

def test_multisheet_only_assertion_sheet_filled(tmp_path):
    fp = tmp_path / "sva_only.xlsx"
    _make_sva_workbook(fp, row_ids=["SVA-1", "SVA-2"])

    rows = parse_excel_multisheet(fp)

    assert len(rows) == 2, f"应得 2 条 SVA 行，实际 {len(rows)}"
    assert {r.code_type for r in rows} == {"assertion"}, (
        "所有行 code_type 应为 'assertion'，实际：" + repr([r.code_type for r in rows])
    )
    assert {r.row_id for r in rows} == {"SVA-1", "SVA-2"}


# ── 2. 多 sheet 均有数据：返回混合两类 ──────────────────────────────────

def test_multisheet_both_sheets_filled(tmp_path):
    fp = tmp_path / "dual.xlsx"
    _make_dual_workbook(
        fp, sva_row_ids=["SVA-1"], cov_row_ids=["COV-1", "COV-2"]
    )

    rows = parse_excel_multisheet(fp)

    code_types = [r.code_type for r in rows]
    assert "assertion" in code_types, f"应含 assertion 行：{code_types}"
    assert "coverage" in code_types, f"应含 coverage 行：{code_types}"
    assert len(rows) == 3, f"SVA-1 + COV-1 + COV-2 = 3 行，实际 {len(rows)}"

    by_ct = {r.code_type: [x.row_id for x in rows if x.code_type == r.code_type] for r in rows}
    assert by_ct["assertion"] == ["SVA-1"]
    assert sorted(by_ct["coverage"]) == ["COV-1", "COV-2"]


# ── 3. 全部 sheet 空 → ValueError + 端点 HTTP 400 ───────────────────────

def test_multisheet_all_empty_raises_no_valid_rows(tmp_path):
    """模板原样上传（A 列全空）触发 ValueError("no_valid_rows")。"""
    fp = tmp_path / "empty.xlsx"
    build_template_workbook(get_registry()).save(fp)

    with pytest.raises(ValueError) as exc_info:
        parse_excel_multisheet(fp)
    assert str(exc_info.value) == "no_valid_rows"


def test_preflight_no_valid_rows_returns_400_with_structured_detail():
    """空模板走 POST /batch/preflight（不传 code_type）应得 HTTP 400 +
    detail.type == "no_valid_rows"，文案含"未检测到任何有效数据行"。"""
    client = TestClient(_build_authed_app())

    buf = BytesIO()
    build_template_workbook(get_registry()).save(buf)
    buf.seek(0)

    resp = client.post(
        "/api/v1/batch/preflight",
        files={"file": ("template.xlsx", buf.read(),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        # 故意不传 data={"code_type": ...} —— 走 multisheet 分支
    )

    assert resp.status_code == 400, (
        f"空模板 preflight 应返回 400，实际 {resp.status_code}: {resp.text}"
    )
    body = resp.json()
    assert body["detail"]["type"] == "no_valid_rows", body
    assert "未检测到任何有效数据行" in body["detail"]["message"]


def test_preflight_corrupted_xlsx_returns_400_not_500():
    """M2: 损坏 .xlsx 文件应被翻成 HTTP 400 + 通用文案，而非以 500 暴露内部异常。"""
    client = TestClient(_build_authed_app())

    resp = client.post(
        "/api/v1/batch/preflight",
        files={"file": ("garbage.xlsx", b"not a real xlsx",
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert resp.status_code == 400, (
        f"损坏 .xlsx 应返回 400，实际 {resp.status_code}: {resp.text}"
    )
    body = resp.json()
    # 不应外泄底层 openpyxl/zipfile 异常 message，只用通用提示文案。
    detail = body["detail"]
    msg = detail if isinstance(detail, str) else detail.get("message", "")
    assert "Excel" in msg or "无法读取" in msg, body


# ── 4. 未知 sheet 静默跳过 ──────────────────────────────────────────────

def test_multisheet_unknown_sheet_silently_skipped(tmp_path):
    fp = tmp_path / "with_garbage.xlsx"
    _make_unknown_sheet_workbook(fp, sva_row_ids=["SVA-1"])

    rows = parse_excel_multisheet(fp)

    assert len(rows) == 1, f"应只返回 SVA-1 一行，实际 {len(rows)}：{[r.row_id for r in rows]}"
    assert rows[0].row_id == "SVA-1"
    assert rows[0].code_type == "assertion"
    # 未知 sheet 的 GARBAGE-1 行不应出现
    assert all(r.row_id != "GARBAGE-1" for r in rows)


# ── 5. gate 2 批量文案含 "sheet" 关键词 ────────────────────────────────

def test_gate2_batch_reason_contains_sheet_keyword():
    """`_build_code_type_mismatch_reason` 输出含 "sheet" 关键词 + selected sheet
    名 + suggested code_type，验证 FEAT-18 文案覆盖生效。"""
    reason = _build_code_type_mismatch_reason(
        selected_code_type="assertion",
        suggested_code_type="coverage",
    )
    # "sheet" 关键词必须出现——这是批量场景区别于单条页文案的核心差异
    assert "sheet" in reason, f"reason 缺 'sheet' 关键词：{reason!r}"
    # selected 的 sheet 名（SVA需求）应反查到位
    assert "SVA需求" in reason, f"reason 缺 selected sheet 名 'SVA需求'：{reason!r}"
    # suggested code_type 必须明示
    assert "coverage" in reason, f"reason 缺 suggested code_type 'coverage'：{reason!r}"


def test_gate2_batch_reason_unknown_code_type_falls_back_gracefully():
    """selected_code_type 不在 registry 中时 helper 不应抛异常——退化为字面量。"""
    reason = _build_code_type_mismatch_reason(
        selected_code_type="bogus_unknown_type",
        suggested_code_type="assertion",
    )
    # registry.get 失败时退化为 selected_code_type 字面量
    assert "bogus_unknown_type" in reason
    assert "sheet" in reason
