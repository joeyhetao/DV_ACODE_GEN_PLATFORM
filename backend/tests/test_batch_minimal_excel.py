"""FEAT-18 — 最小可上传 Excel 的 preflight / parse 路径回归测试。

本文件刻意以"含 1 数据行的最小可上传 workbook"为测试基线，确保：

- **向后兼容路径**（传 `data={"code_type": ...}`）：旧版前端 / 历史脚本调
  `POST /batch/preflight` 时附 `code_type` 表单字段，端点应走单 sheet 解析路径，
  返回的每条 PreflightRowResult 都带正确的 `code_type` 字段（默认空串字段已
  填值）。
- **FEAT-18 新路径**（不传 `code_type`）：同一份 Excel 不传 code_type 时走
  `parse_excel_multisheet`，结果按 sheet 真实归属标注 code_type。

跑法：
    docker compose exec backend pytest tests/test_batch_minimal_excel.py -v
"""
from __future__ import annotations

from io import BytesIO
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.batch import router as batch_router
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.services.parser.template_writer import build_template_workbook
from app.services.registry import get_registry


def _make_user() -> User:
    u = MagicMock(spec=User)
    u.id = "user-1"
    u.role = "user"
    return u


@pytest.fixture
def authed_client(monkeypatch):
    """挂 batch router + override auth/db + mock 掉 preflight_row。

    `preflight_row` 真实实现走 RAG / embedding service，单测不能依赖。这里以 monkeypatch
    替换为 AsyncMock，回返固定 estimated_confidence 0.9 + top_match 占位。
    """
    app = FastAPI()
    app.include_router(batch_router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: _make_user()

    async def _noop_db():
        yield MagicMock()
    app.dependency_overrides[get_db] = _noop_db

    async def _fake_preflight_row(row_id: str, intent_text: str) -> dict[str, Any]:
        return {
            "row_id": row_id,
            "estimated_confidence": 0.9,
            "top_match": {"name": "fake_template_v1"},
        }
    # 注意：batch.py 在模块顶部 from app.services.intent.preflight import preflight_row
    # 所以要 patch 端点模块上的引用。
    monkeypatch.setattr("app.api.v1.batch.preflight_row", _fake_preflight_row)

    return TestClient(app)


def _build_minimal_workbook(sva_rows: list[str] = None, cov_rows: list[str] = None) -> BytesIO:
    """FEAT-19: schema 精简后 SVA 与 Coverage 两 sheet 均为 3 列（A row_id /
    B intent / C 备注），最小可解析数据行只需写 A + B。"""
    sva_rows = sva_rows or []
    cov_rows = cov_rows or []
    wb = build_template_workbook(get_registry())
    if sva_rows:
        ws_sva = wb["SVA需求"]
        for i, rid in enumerate(sva_rows, start=3):
            ws_sva.cell(row=i, column=1, value=rid)
            ws_sva.cell(row=i, column=2, value=f"sva intent {rid}")
    if cov_rows:
        ws_cov = wb["Coverage需求"]
        for i, rid in enumerate(cov_rows, start=3):
            ws_cov.cell(row=i, column=1, value=rid)
            ws_cov.cell(row=i, column=2, value=f"cov intent {rid}")
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


# ── 向后兼容路径：显式传 code_type，走单 sheet 路径 ─────────────────────

def test_preflight_with_explicit_code_type_uses_legacy_path(authed_client):
    """spec §3 Out: parse_excel(file, code_type) 旧签名向后兼容。显式 code_type
    仍走单 sheet 路径，preflight 结果每行 code_type 字段被填为传入值。"""
    buf = _build_minimal_workbook(sva_rows=["SVA-1"])
    resp = authed_client.post(
        "/api/v1/batch/preflight",
        files={"file": ("input.xlsx", buf.read(),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"code_type": "assertion"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["results"]) == 1
    row = body["results"][0]
    assert row["row_id"] == "SVA-1"
    assert row["code_type"] == "assertion"


# ── FEAT-18 新路径：不传 code_type，走 multisheet 自动检测 ───────────────

def test_preflight_without_code_type_uses_multisheet_path(authed_client):
    """spec AC §2: 不传 code_type → multisheet 自动检测；每行 code_type
    按所在 sheet 真实归属填充。"""
    buf = _build_minimal_workbook(sva_rows=["SVA-1"], cov_rows=["COV-1"])
    resp = authed_client.post(
        "/api/v1/batch/preflight",
        files={"file": ("input.xlsx", buf.read(),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        # 关键：不传 data={"code_type": ...}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["results"]) == 2

    by_id = {r["row_id"]: r for r in body["results"]}
    assert by_id["SVA-1"]["code_type"] == "assertion", by_id["SVA-1"]
    assert by_id["COV-1"]["code_type"] == "coverage", by_id["COV-1"]


def test_preflight_without_code_type_only_sva_filled(authed_client):
    """只 SVA sheet 有数据：multisheet 路径行为与单 sheet 模式等同。"""
    buf = _build_minimal_workbook(sva_rows=["SVA-1", "SVA-2"])
    resp = authed_client.post(
        "/api/v1/batch/preflight",
        files={"file": ("input.xlsx", buf.read(),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["results"]) == 2
    assert {r["code_type"] for r in body["results"]} == {"assertion"}
