"""FEAT-11 Stage 2 端点 + 缓存 + analytics filter 单测.

测 POST /api/v1/generate/llm-fallback 端点的业务逻辑，以及 admin analytics 的
generation_mode 过滤参数行为。LLM / Redis / DB 全部 mock，无外部依赖。

跑法（容器内）:
    docker compose exec backend pytest tests/test_llm_direct_generation.py -v
"""
from __future__ import annotations
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.api.v1.generate import llm_fallback
from app.api.v1.admin import (
    analytics_feedback_summary,
    analytics_template_issues,
)
from app.schemas.generate import LLMFallbackRequest
from app.services.core.cache import (
    _canonical_llm_direct_signature,
    _make_llm_direct_key,
)


def _autofill_id_add(captured: list):
    """模拟 SQLAlchemy commit-time UUID default：db.add(record) 时立刻分配一个 id。

    生产环境里 GenerationRecord.id 的 mapped_column(default=lambda: uuid4()) 在 flush
    时（commit 内部）由 SQLAlchemy 评估；我们的 MagicMock 不真正 flush，故手工模拟，
    让端点之后访问 record.id 不为 None（否则 Pydantic 校验 generation_record_id 失败）。
    """
    import uuid

    def _add(rec):
        if getattr(rec, "id", None) in (None, ""):
            rec.id = str(uuid.uuid4())
        captured.append(rec)

    return _add


def _make_source_record(
    record_id: str = "rec-1",
    generation_mode: str = "rag",
    template_id: str | None = "tpl-1",
    original_intent: str = "axi 握手稳定性断言",
    params_used: dict | None = None,
):
    """构造一条 fake GenerationRecord 作为源记录。"""
    rec = MagicMock()
    rec.id = record_id
    rec.generation_mode = generation_mode
    rec.template_id = template_id
    rec.original_intent = original_intent
    rec.normalized_intent = original_intent
    rec.intent_hash = "hash-abc"
    rec.params_used = params_used or {"clk": "aclk", "rst": "aresetn", "valid": "v"}
    return rec


def _user():
    u = MagicMock()
    u.id = "user-1"
    return u


def _admin_user():
    u = MagicMock()
    u.id = "admin-1"
    u.role = "lib_admin"
    return u


def _scalar_result(value):
    r = MagicMock()
    r.scalar = MagicMock(return_value=value)
    return r


def _all_result(rows):
    r = MagicMock()
    r.all = MagicMock(return_value=rows)
    return r


# ── 1) /generate/llm-fallback：源记录不存在 → 404 ────────────────────────

@pytest.mark.asyncio
async def test_llm_fallback_source_not_found_returns_404():
    db = MagicMock()
    db.get = AsyncMock(return_value=None)
    db.add = MagicMock()
    db.commit = AsyncMock()

    with pytest.raises(HTTPException) as excinfo:
        await llm_fallback(
            payload=LLMFallbackRequest(generation_record_id="missing"),
            db=db,
            current_user=_user(),
        )
    assert excinfo.value.status_code == 404


# ── 2) 源记录已是 llm_direct → 422 (拒链式) ─────────────────────────────

@pytest.mark.asyncio
async def test_llm_fallback_chained_llm_direct_rejected_with_422():
    src = _make_source_record(generation_mode="llm_direct", template_id=None)
    db = MagicMock()
    db.get = AsyncMock(return_value=src)

    with pytest.raises(HTTPException) as excinfo:
        await llm_fallback(
            payload=LLMFallbackRequest(generation_record_id="rec-1"),
            db=db,
            current_user=_user(),
        )
    assert excinfo.value.status_code == 422
    detail = excinfo.value.detail
    assert isinstance(detail, dict)
    assert detail.get("type") == "llm_direct_chained_not_allowed"


# ── 3) 缓存命中 → 不调 LLM；返回缓存代码；新建子记录 cache_hit=True ───────

@pytest.mark.asyncio
async def test_llm_fallback_cache_hit_returns_cached_code_without_llm_call(monkeypatch):
    cached_code = "// CACHED CODE"
    src = _make_source_record()
    fake_tmpl = MagicMock()
    fake_tmpl.code_type = "assertion"

    async def fake_db_get(model, ident):
        # 第一次取 GenerationRecord，第二次取 Template
        if hasattr(model, "__tablename__") and model.__tablename__ == "templates":
            return fake_tmpl
        # 简化：record 命中 src
        if ident == src.id:
            return src
        return fake_tmpl

    db = MagicMock()
    db.get = AsyncMock(side_effect=fake_db_get)
    added_records: list = []
    db.add = MagicMock(side_effect=_autofill_id_add(added_records))
    db.commit = AsyncMock()

    fake_llm = MagicMock()
    fake_llm.config_id = "cfg-1"
    fake_llm.generate_code_freeform = AsyncMock(side_effect=AssertionError("不应被调"))

    monkeypatch.setattr(
        "app.api.v1.generate.get_llm_direct_cache",
        AsyncMock(return_value=cached_code),
    )
    set_cache_mock = AsyncMock()
    monkeypatch.setattr("app.api.v1.generate.set_llm_direct_cache", set_cache_mock)
    monkeypatch.setattr(
        "app.api.v1.generate.get_default_llm_client",
        AsyncMock(return_value=fake_llm),
    )
    monkeypatch.setattr(
        "app.api.v1.generate.get_default_llm_config_id",
        AsyncMock(return_value="cfg-1"),
    )

    resp = await llm_fallback(
        payload=LLMFallbackRequest(generation_record_id=src.id),
        db=db,
        current_user=_user(),
    )

    assert resp.code == cached_code
    assert resp.cache_hit is True
    assert resp.generation_mode == "llm_direct"
    # 缓存命中不应写 set_llm_direct_cache
    set_cache_mock.assert_not_awaited()
    # 仍创建了新 record（让用户对 llm_direct 结果独立反馈）
    assert len(added_records) == 1
    added_record = added_records[0]
    assert added_record.generation_mode == "llm_direct"
    assert added_record.parent_record_id == src.id
    assert added_record.template_id is None
    assert added_record.cache_hit is True


# ── 4) 缓存 miss → 调 LLM → 写新记录 + 写缓存 ────────────────────────────

@pytest.mark.asyncio
async def test_llm_fallback_cache_miss_calls_llm_and_writes_cache(monkeypatch):
    src = _make_source_record()
    fake_tmpl = MagicMock()
    fake_tmpl.code_type = "assertion"

    async def fake_db_get(model, ident):
        if ident == src.id:
            return src
        return fake_tmpl

    db = MagicMock()
    db.get = AsyncMock(side_effect=fake_db_get)
    added_records: list = []
    db.add = MagicMock(side_effect=_autofill_id_add(added_records))
    db.commit = AsyncMock()

    fake_llm = MagicMock()
    fake_llm.config_id = "cfg-1"
    fake_llm.generate_code_freeform = AsyncMock(return_value="// FRESH CODE")

    monkeypatch.setattr(
        "app.api.v1.generate.get_llm_direct_cache",
        AsyncMock(return_value=None),
    )
    set_cache_mock = AsyncMock()
    monkeypatch.setattr("app.api.v1.generate.set_llm_direct_cache", set_cache_mock)
    monkeypatch.setattr(
        "app.api.v1.generate.get_default_llm_client",
        AsyncMock(return_value=fake_llm),
    )
    monkeypatch.setattr(
        "app.api.v1.generate.get_default_llm_config_id",
        AsyncMock(return_value="cfg-1"),
    )

    resp = await llm_fallback(
        payload=LLMFallbackRequest(generation_record_id=src.id),
        db=db,
        current_user=_user(),
    )

    assert resp.code == "// FRESH CODE"
    assert resp.cache_hit is False
    assert resp.generation_mode == "llm_direct"
    fake_llm.generate_code_freeform.assert_awaited_once()
    set_cache_mock.assert_awaited_once()
    # 新记录 generation_mode='llm_direct' + parent_record_id=src.id + template_id=None
    assert len(added_records) == 1
    added_record = added_records[0]
    assert added_record.generation_mode == "llm_direct"
    assert added_record.parent_record_id == src.id
    assert added_record.template_id is None
    assert added_record.output_code == "// FRESH CODE"


# ── 5) LLM 抛 no_sv_code_block → 422 llm_direct_no_code ─────────────────

@pytest.mark.asyncio
async def test_llm_fallback_no_sv_code_block_raises_422(monkeypatch):
    src = _make_source_record()
    fake_tmpl = MagicMock()
    fake_tmpl.code_type = "assertion"

    async def fake_db_get(model, ident):
        if ident == src.id:
            return src
        return fake_tmpl

    db = MagicMock()
    db.get = AsyncMock(side_effect=fake_db_get)
    db.add = MagicMock()
    db.commit = AsyncMock()

    fake_llm = MagicMock()
    fake_llm.config_id = "cfg-1"
    fake_llm.generate_code_freeform = AsyncMock(side_effect=ValueError("no_sv_code_block"))

    monkeypatch.setattr(
        "app.api.v1.generate.get_llm_direct_cache",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        "app.api.v1.generate.set_llm_direct_cache",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "app.api.v1.generate.get_default_llm_client",
        AsyncMock(return_value=fake_llm),
    )
    monkeypatch.setattr(
        "app.api.v1.generate.get_default_llm_config_id",
        AsyncMock(return_value="cfg-1"),
    )

    with pytest.raises(HTTPException) as excinfo:
        await llm_fallback(
            payload=LLMFallbackRequest(generation_record_id=src.id),
            db=db,
            current_user=_user(),
        )
    assert excinfo.value.status_code == 422
    detail = excinfo.value.detail
    assert isinstance(detail, dict)
    assert detail.get("type") == "llm_direct_no_code"


# ── 6) 缓存 key canonical：signal 顺序无关 ─────────────────────────────

def test_canonical_signature_signals_order_independent():
    sig_a = _canonical_llm_direct_signature(
        intent="x", code_type="assertion",
        signals=[{"name": "b"}, {"name": "a"}],
        clk="clk", rst="rst",
    )
    sig_b = _canonical_llm_direct_signature(
        intent="x", code_type="assertion",
        signals=[{"name": "a"}, {"name": "b"}],
        clk="clk", rst="rst",
    )
    assert sig_a == sig_b


def test_canonical_signature_differs_by_input():
    """intent / code_type / clk / rst 任一变化都换 key（防误命中）。"""
    base = _canonical_llm_direct_signature(
        intent="x", code_type="assertion", signals=[], clk="clk", rst="rst",
    )
    assert base != _canonical_llm_direct_signature(
        intent="y", code_type="assertion", signals=[], clk="clk", rst="rst",
    )
    assert base != _canonical_llm_direct_signature(
        intent="x", code_type="coverage", signals=[], clk="clk", rst="rst",
    )
    assert base != _canonical_llm_direct_signature(
        intent="x", code_type="assertion", signals=[], clk="aclk", rst="rst",
    )
    assert base != _canonical_llm_direct_signature(
        intent="x", code_type="assertion", signals=[], clk="clk", rst="aresetn",
    )


def test_make_llm_direct_key_includes_config_bucket():
    sig = "abc123"
    assert _make_llm_direct_key(sig, "cfg-1") == "gen_llm:cfg-1:abc123"
    # 空 config_id → "_" 占位（与 gen:* 一致）
    assert _make_llm_direct_key(sig, "") == "gen_llm:_:abc123"


# ── 7) Analytics generation_mode filter ────────────────────────────────

@pytest.mark.asyncio
async def test_feedback_summary_filter_by_generation_mode_llm_direct():
    """generation_mode='llm_direct' → 只统计 llm_direct 路径的记录。"""
    db = MagicMock()
    db.execute = AsyncMock(side_effect=[
        _scalar_result(20),   # total_generations（llm_direct only）
        _scalar_result(10),   # total_feedbacks
        _scalar_result(4),    # bad_feedbacks
        _scalar_result(0),    # no_match_count（llm_direct 不走 gate）
    ])
    res = await analytics_feedback_summary(
        days=7, generation_mode="llm_direct", db=db, current_user=_admin_user()
    )
    assert res["generation_mode"] == "llm_direct"
    assert res["total_generations"] == 20
    assert res["bad_rate"] == 0.4
    assert res["no_match_rate"] == 0.0


@pytest.mark.asyncio
async def test_feedback_summary_invalid_generation_mode_returns_400():
    db = MagicMock()
    db.execute = AsyncMock()
    with pytest.raises(HTTPException) as excinfo:
        await analytics_feedback_summary(
            days=7, generation_mode="bogus", db=db, current_user=_admin_user()
        )
    assert excinfo.value.status_code == 400


@pytest.mark.asyncio
async def test_template_issues_llm_direct_groups_null_into_bucket():
    """generation_mode='llm_direct' → template_id IS NULL 行归入 '__llm_direct__' 桶。"""
    rows = [
        SimpleNamespace(template_id=None, total_count=10, bad_count=4),
    ]
    db = MagicMock()
    db.execute = AsyncMock(return_value=_all_result(rows))
    res = await analytics_template_issues(
        days=7, limit=10, generation_mode="llm_direct",
        db=db, current_user=_admin_user(),
    )
    assert len(res) == 1
    assert res[0]["template_id"] == "__llm_direct__"
    assert res[0]["bad_rate"] == 0.4
