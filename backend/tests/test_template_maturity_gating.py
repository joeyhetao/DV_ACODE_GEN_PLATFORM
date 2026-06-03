"""FEAT-13 模板成熟度门控单测。

覆盖：
- stage1_hybrid_search 的 Qdrant Filter 含 maturity_level='production' 条件
- engine.dense_top1_score Qdrant Filter 含 maturity_level='production' 条件
- engine.rag_retrieve DB 二次过滤拦截非 production 模板
- update_template PATCH 权限校验：super_admin 200 / lib_admin 403 / 非法值 422
- migration 009 backfill 条件函数（sva_/cov_ → production，其余 → experimental，
  is_active=false 行也归 experimental）

跑法（容器内）:
    docker compose exec backend pytest tests/test_template_maturity_gating.py -v

测试不依赖 live LLM / Qdrant / PG，全部用 unittest.mock 桩 + 内嵌 backfill 规则函数。
"""
from __future__ import annotations
import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from qdrant_client.models import FieldCondition, MatchValue

from app.api.v1.templates import create_template, update_template
from app.models.user import User
from app.schemas.template import TemplateCreate, TemplateUpdate


# ── Block A：migration 009 backfill 规则函数（与 SQL 正则一致，便于单测）─────

_MIGRATION_009_PRODUCTION_RE = re.compile(r"^(sva|cov)_.+_v[0-9]+$")


def _expected_maturity_level(template_id: str) -> str:
    """复现 migration 009 backfill SQL 的判定逻辑（is_active 不参与判定，
    server_default 已把所有行先置 experimental，再 UPDATE 命中规范的升 production）。"""
    return "production" if _MIGRATION_009_PRODUCTION_RE.match(template_id) else "experimental"


@pytest.mark.parametrize(
    "tmpl_id,expected",
    [
        ("sva_handshake_stable_v1", "production"),
        ("sva_axi_aw_stable_v2", "production"),
        ("cov_fsm_state_v1", "production"),
        ("cov_protocol_handshake_v3", "production"),
        ("L6_E2E_1778770719", "experimental"),
        ("user_contrib_foo_v1", "experimental"),
        ("sva_no_version_suffix", "experimental"),
        ("svax_unrelated_v1", "experimental"),
        ("", "experimental"),
    ],
)
def test_backfill_rule_classification(tmpl_id: str, expected: str):
    assert _expected_maturity_level(tmpl_id) == expected


def test_backfill_is_active_false_row_also_gets_experimental():
    """is_active=false 的行不走特殊路径——同样按 id 规范判定。
    `L6_E2E_*` 即便手动停用，依然 experimental（非 production）。"""
    assert _expected_maturity_level("L6_E2E_999") == "experimental"
    assert _expected_maturity_level("sva_dead_v9") == "production"  # 即便停用仍按规范判


# ── Block B：stage1_hybrid_search Qdrant Filter 含 maturity_level ─────────


@pytest.mark.asyncio
async def test_stage1_filter_includes_maturity_level_production():
    """stage1_hybrid_search 默认 maturity_level='production'，Qdrant Prefetch 的
    filter.must 中应同时包含 code_type 和 maturity_level=production 两个 FieldCondition。"""
    from app.services.rag import stage1_hybrid as mod

    fake_qdrant = MagicMock()
    fake_qdrant.query_points = AsyncMock(return_value=MagicMock(points=[]))
    fake_settings = MagicMock(qdrant_collection="templates", rag_stage1_top_k=20)

    with patch.object(mod, "get_qdrant", return_value=fake_qdrant), \
            patch.object(mod, "get_settings", return_value=fake_settings):
        await mod.stage1_hybrid_search(
            dense_vec=[0.1] * 4,
            sparse_vec={"1": 0.5},
            top_k=5,
            code_type="assertion",
        )

    call_kwargs = fake_qdrant.query_points.await_args.kwargs
    prefetch = call_kwargs["prefetch"]
    assert len(prefetch) == 2  # dense + sparse 都带相同 filter
    for pf in prefetch:
        f = pf.filter
        assert f is not None, "stage1 必须设置 Filter"
        must_fields = {c.key: c.match.value for c in f.must}
        assert must_fields.get("code_type") == "assertion"
        assert must_fields.get("maturity_level") == "production", (
            "FEAT-13 maturity 门控：stage1 必须默认仅召回 production"
        )


@pytest.mark.asyncio
async def test_stage1_filter_respects_overridden_maturity_level():
    """显式传 maturity_level='experimental' 时 Filter 必须随之改变（admin 调试用预留）。"""
    from app.services.rag import stage1_hybrid as mod

    fake_qdrant = MagicMock()
    fake_qdrant.query_points = AsyncMock(return_value=MagicMock(points=[]))
    fake_settings = MagicMock(qdrant_collection="templates", rag_stage1_top_k=20)

    with patch.object(mod, "get_qdrant", return_value=fake_qdrant), \
            patch.object(mod, "get_settings", return_value=fake_settings):
        await mod.stage1_hybrid_search(
            dense_vec=[0.1] * 4,
            sparse_vec={"1": 0.5},
            top_k=5,
            maturity_level="experimental",
        )

    pf0 = fake_qdrant.query_points.await_args.kwargs["prefetch"][0]
    must_fields = {c.key: c.match.value for c in pf0.filter.must}
    assert must_fields.get("maturity_level") == "experimental"


# ── Block C：engine.dense_top1_score 含 maturity_level Filter ────────────


@pytest.mark.asyncio
async def test_dense_top1_score_filter_includes_maturity_level():
    """off-topic gate / code_type mismatch gate 用的 dense_top1_score
    必须仅在 production 子集上打分，否则 experimental 模板会拉高 top1，
    遮蔽真正的 off-topic 信号。"""
    from app.services.rag import engine as mod

    fake_qdrant = MagicMock()
    fake_qdrant.query_points = AsyncMock(return_value=MagicMock(points=[]))
    fake_embed = MagicMock()
    fake_embed.embed = AsyncMock(return_value={"dense": [[0.1] * 4]})
    fake_settings = MagicMock(qdrant_collection="templates")

    with patch.object(mod, "get_qdrant", return_value=fake_qdrant), \
            patch.object(mod, "get_embedding_client", return_value=fake_embed), \
            patch.object(mod, "get_settings", return_value=fake_settings):
        await mod.dense_top1_score("写一个 axi 断言", code_type="assertion")

    qf = fake_qdrant.query_points.await_args.kwargs["query_filter"]
    must_fields = {c.key: c.match.value for c in qf.must}
    assert must_fields.get("maturity_level") == "production"
    assert must_fields.get("code_type") == "assertion"


@pytest.mark.asyncio
async def test_dense_top1_score_filter_without_code_type_still_filters_maturity():
    """code_type 不传时仍需保留 maturity_level 过滤——否则会污染 off-topic 阈值。"""
    from app.services.rag import engine as mod

    fake_qdrant = MagicMock()
    fake_qdrant.query_points = AsyncMock(return_value=MagicMock(points=[]))
    fake_embed = MagicMock()
    fake_embed.embed = AsyncMock(return_value={"dense": [[0.1] * 4]})
    fake_settings = MagicMock(qdrant_collection="templates")

    with patch.object(mod, "get_qdrant", return_value=fake_qdrant), \
            patch.object(mod, "get_embedding_client", return_value=fake_embed), \
            patch.object(mod, "get_settings", return_value=fake_settings):
        await mod.dense_top1_score("空 code_type 场景")

    qf = fake_qdrant.query_points.await_args.kwargs["query_filter"]
    must_fields = {c.key: c.match.value for c in qf.must}
    assert must_fields.get("maturity_level") == "production"


# ── Block D：engine.rag_retrieve DB 二次过滤 ────────────────────────────


@pytest.mark.asyncio
async def test_rag_retrieve_db_query_filters_non_production():
    """即便 stage1 漏入了非 production 模板（payload 旧 / 漂移），engine.py 的
    DB 查询 where 也必须含 maturity_level=='production'，作为兜底拦截。"""
    from app.services.rag import engine as mod

    fake_embed = MagicMock()
    fake_embed.embed = AsyncMock(return_value={
        "dense": [[0.1] * 4],
        "sparse": [{"1": 0.5}],
        "colbert": [[[0.1] * 4]],
    })
    fake_settings = MagicMock(
        qdrant_collection="templates",
        rag_stage1_top_k=20,
        rag_stage2_top_k=10,
        rag_stage3_top_k=5,
    )

    # stage1 返回两个候选；stage2 透传；DB 模拟只查到 production 的那条
    stage1_result = [
        {"qdrant_id": "p1", "template_id": "sva_official_v1", "score": 0.9, "colbert_vec": None, "payload": {}},
        {"qdrant_id": "p2", "template_id": "L6_E2E_1234", "score": 0.85, "colbert_vec": None, "payload": {}},
    ]

    async def fake_stage1(**kwargs):
        # 同时校验调用时 maturity_level='production'
        assert kwargs.get("maturity_level") == "production"
        return stage1_result

    async def fake_stage3(**kwargs):
        return kwargs["stage2_results"]

    captured_stmt: dict = {}

    class FakeScalars:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return self._rows

    class FakeResult:
        def __init__(self, rows):
            self._rows = rows

        def scalars(self):
            return FakeScalars(self._rows)

    fake_tmpl = MagicMock()
    fake_tmpl.id = "sva_official_v1"
    fake_tmpl.name = "official handshake"
    fake_tmpl.description = "desc"
    fake_tmpl.keywords = ["axi"]

    captured_where_repr: list[str] = []

    async def fake_execute(stmt):
        # 截 SQL where 子句的 str 形态用于断言（asyncpg 不会真执行）
        captured_where_repr.append(str(stmt.whereclause))
        return FakeResult([fake_tmpl])

    fake_db = MagicMock()
    fake_db.execute = fake_execute

    with patch.object(mod, "get_embedding_client", return_value=fake_embed), \
            patch.object(mod, "get_settings", return_value=fake_settings), \
            patch.object(mod, "stage1_hybrid_search", side_effect=fake_stage1), \
            patch.object(mod, "stage3_rerank", side_effect=fake_stage3):
        out = await mod.rag_retrieve("intent", fake_db, code_type="assertion")

    assert captured_where_repr, "rag_retrieve 必须执行 DB 查询"
    where_str = captured_where_repr[0]
    assert "maturity_level" in where_str, (
        f"engine.rag_retrieve DB 查询必须含 maturity_level 过滤，实际: {where_str}"
    )
    # 输出只剩 production 模板，L6_E2E_* 被 templates_by_id 过滤掉
    assert len(out) == 1
    assert out[0]["template_id"] == "sva_official_v1"


# ── Block E：PATCH /templates/{id} maturity_level 权限校验 ──────────────


def _make_user(role: str) -> User:
    u = MagicMock(spec=User)
    u.id = f"user-{role}"
    u.role = role
    return u


def _make_db_with_template(tmpl) -> MagicMock:
    db = MagicMock()
    db.get = AsyncMock(return_value=tmpl)
    db.commit = AsyncMock(return_value=None)
    db.refresh = AsyncMock(return_value=None)
    db.add = MagicMock()
    return db


def _make_template(maturity_level: str = "experimental"):
    tmpl = MagicMock()
    tmpl.id = "sva_test_v1"
    tmpl.version = "1.0.0"
    tmpl.name = "test"
    tmpl.description = "desc"
    tmpl.parameters = []
    tmpl.template_body = "assert(1)"
    tmpl.maturity = "draft"
    tmpl.maturity_level = maturity_level
    tmpl.tags = []
    tmpl.keywords = []
    tmpl.related_ids = []
    tmpl.sync_status = "ok"
    return tmpl


@pytest.mark.asyncio
async def test_patch_maturity_level_lib_admin_forbidden_403():
    """lib_admin 触碰 maturity_level → 403，且模板字段未被修改。"""
    tmpl = _make_template(maturity_level="experimental")
    db = _make_db_with_template(tmpl)
    user = _make_user("lib_admin")
    payload = TemplateUpdate(maturity_level="production")

    with patch("app.api.v1.templates.invalidate_template_cache", new=AsyncMock()):
        with pytest.raises(HTTPException) as exc_info:
            await update_template("sva_test_v1", payload, db=db, current_user=user)
    assert exc_info.value.status_code == 403
    assert "super_admin" in exc_info.value.detail
    # 没有进入修改流程
    db.commit.assert_not_called()
    assert tmpl.maturity_level == "experimental"


@pytest.mark.asyncio
async def test_patch_maturity_level_super_admin_succeeds():
    """super_admin 可成功升级为 production，commit + invalidate_cache 都被调用。"""
    tmpl = _make_template(maturity_level="experimental")
    db = _make_db_with_template(tmpl)
    user = _make_user("super_admin")
    payload = TemplateUpdate(maturity_level="production", change_note="approved")

    with patch("app.api.v1.templates.invalidate_template_cache", new=AsyncMock()) as inv, \
            patch("app.api.v1.templates.validate_template_syntax"):
        result = await update_template("sva_test_v1", payload, db=db, current_user=user)
    assert result is tmpl
    assert tmpl.maturity_level == "production"
    db.commit.assert_awaited_once()
    inv.assert_awaited_once_with("sva_test_v1")


@pytest.mark.asyncio
async def test_patch_other_fields_lib_admin_still_allowed():
    """lib_admin 只要不触碰 maturity_level，其他字段照常可改（描述 / template_body）。"""
    tmpl = _make_template(maturity_level="experimental")
    db = _make_db_with_template(tmpl)
    user = _make_user("lib_admin")
    payload = TemplateUpdate(description="updated desc")

    with patch("app.api.v1.templates.invalidate_template_cache", new=AsyncMock()):
        await update_template("sva_test_v1", payload, db=db, current_user=user)
    assert tmpl.description == "updated desc"
    # maturity_level 未被触碰
    assert tmpl.maturity_level == "experimental"
    db.commit.assert_awaited_once()


def test_patch_invalid_maturity_level_value_pydantic_422():
    """Pydantic Literal 自动拦截非法值。前端传 'gold_standard' 之类直接 422。"""
    with pytest.raises(ValidationError):
        TemplateUpdate(maturity_level="gold_standard")
    with pytest.raises(ValidationError):
        TemplateUpdate(maturity_level="")
    with pytest.raises(ValidationError):
        TemplateUpdate(maturity_level="PRODUCTION")  # 大小写敏感


def test_template_update_maturity_level_optional_none_ok():
    """不传 maturity_level（None）是合法 partial update，不触发 403。"""
    payload = TemplateUpdate(description="just desc")
    assert payload.maturity_level is None


# ── Block F：POST /templates 同步收口 maturity_level 特权 ───────────────


def _make_template_create_payload(**overrides) -> TemplateCreate:
    base = dict(
        id="sva_new_v1",
        version="1.0.0",
        name="sva_new_v1",
        code_type="assertion",
        description="d",
        parameters=[],
        template_body="assert(1)",
    )
    base.update(overrides)
    return TemplateCreate(**base)


@pytest.mark.asyncio
async def test_create_template_lib_admin_default_experimental_allowed():
    """lib_admin 不传 maturity_level → 用 schema 默认 'experimental' → 允许。"""
    payload = _make_template_create_payload()
    assert payload.maturity_level == "experimental"
    db = MagicMock()
    db.add = MagicMock()
    db.commit = AsyncMock(return_value=None)
    db.refresh = AsyncMock(return_value=None)
    user = _make_user("lib_admin")

    with patch("app.api.v1.templates.check_name_duplicate", new=AsyncMock(return_value=False)), \
            patch("app.api.v1.templates.check_semantic_duplicate", new=AsyncMock(return_value=[])), \
            patch("app.api.v1.templates.validate_template_syntax"):
        result = await create_template(payload, force=True, db=db, current_user=user)
    db.add.assert_called_once()
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_template_lib_admin_cannot_set_production():
    """lib_admin 显式提交 maturity_level='production' → 403，绕过升级流程被拦。"""
    payload = _make_template_create_payload(maturity_level="production")
    db = MagicMock()
    db.add = MagicMock()
    db.commit = AsyncMock(return_value=None)
    user = _make_user("lib_admin")

    with pytest.raises(HTTPException) as exc_info:
        await create_template(payload, force=True, db=db, current_user=user)
    assert exc_info.value.status_code == 403
    assert "super_admin" in exc_info.value.detail
    db.add.assert_not_called()
    db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_create_template_lib_admin_cannot_set_draft_either():
    """显式 draft 也算特权操作——同样 403（只允许默认 experimental）。"""
    payload = _make_template_create_payload(maturity_level="draft")
    db = MagicMock()
    db.add = MagicMock()
    db.commit = AsyncMock(return_value=None)
    user = _make_user("lib_admin")

    with pytest.raises(HTTPException) as exc_info:
        await create_template(payload, force=True, db=db, current_user=user)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_create_template_super_admin_can_set_production():
    """super_admin 可在创建时直接设 production。"""
    payload = _make_template_create_payload(maturity_level="production")
    db = MagicMock()
    db.add = MagicMock()
    db.commit = AsyncMock(return_value=None)
    db.refresh = AsyncMock(return_value=None)
    user = _make_user("super_admin")

    with patch("app.api.v1.templates.check_name_duplicate", new=AsyncMock(return_value=False)), \
            patch("app.api.v1.templates.check_semantic_duplicate", new=AsyncMock(return_value=[])), \
            patch("app.api.v1.templates.validate_template_syntax"):
        await create_template(payload, force=True, db=db, current_user=user)
    db.add.assert_called_once()
    db.commit.assert_awaited_once()


# ── Block G：lib_manager rebuild --all 行为 ─────────────────────────────


class _RebuildScalarsStub:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _RebuildResultStub:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _RebuildScalarsStub(self._rows)


class _RebuildSessionCtx:
    """异步上下文桩，替代 `async with AsyncSessionLocal() as db:`。"""

    def __init__(self, db):
        self._db = db

    async def __aenter__(self):
        return self._db

    async def __aexit__(self, *a):
        return None


async def _rebuild_capture_where(force_all: bool) -> str:
    """跑 lib_manager._rebuild 并捕获 SQL where 子句字符串。

    lib_manager._rebuild 内部 `from app.core.database import AsyncSessionLocal`，
    必须 patch 源模块属性而非 lib_manager 命名空间。
    """
    import lib_manager

    captured: list[str] = []

    async def fake_execute(stmt):
        captured.append(str(stmt.whereclause))
        return _RebuildResultStub([])

    fake_db = MagicMock()
    fake_db.execute = fake_execute

    with patch("app.core.database.AsyncSessionLocal", lambda: _RebuildSessionCtx(fake_db)):
        await lib_manager._rebuild(collection=None, force_all=force_all)
    assert captured, "rebuild 必须执行 DB 查询"
    return captured[0]


@pytest.mark.asyncio
async def test_rebuild_default_only_syncing_rows():
    """默认 rebuild 只查 sync_status='syncing' 的行，不刷新已 'ok' 的存量 payload。"""
    where_str = await _rebuild_capture_where(force_all=False)
    assert "sync_status" in where_str, (
        f"默认 rebuild 必须按 sync_status 过滤，实际 where: {where_str}"
    )


@pytest.mark.asyncio
async def test_rebuild_all_skips_sync_status_filter():
    """--all 模式跳过 sync_status 过滤，全量刷新 payload（FEAT-13 migration 009 部署场景）。"""
    where_str = await _rebuild_capture_where(force_all=True)
    assert "sync_status" not in where_str, (
        f"--all 模式不应按 sync_status 过滤，实际 where: {where_str}"
    )
    # is_active==True 仍保留
    assert "is_active" in where_str
