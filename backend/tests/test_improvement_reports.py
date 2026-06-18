"""FEAT-12: 用户对比报告端点单测.

直接调 handler（与 test_feedback_api.py 相同模式）。AsyncSession 用
unittest.mock 桩，不依赖 live PG / Redis / LLM。覆盖 spec §2 全部 AC：

- POST happy path（categories / note 全空 → 201 + status=pending）
- POST 409 unique violation（detail.type=duplicate_report + existing_report_id）
- POST 422 FK 缺失（detail.type=invalid_record_ref）
- POST 403 普通用户对他人 record 提交（detail.type=forbidden_record_ownership）
- POST 401 由 get_current_user 装饰器层兜底（不在 handler 单测内覆盖；FastAPI
  默认 OAuth2PasswordBearer 缺 token 即 401，参见 [test_feedback_api.py] 的同结构跳过）
- PATCH 422 illegal_status_transition（pending→resolved；resolved→pending）
- GET admin 列表 / 详情 / PATCH：普通用户 → require_role 直调返 403
- GET check：exists 两种状态 + 非属主 user 探测他人 record 永远 exists=false
- 状态机正常流转：pending→in_review→resolved
- 分页 + status / categories filter（mock SQL execute 返预设结果）

跑法：
    docker compose exec backend pytest tests/test_improvement_reports.py -v
"""
from __future__ import annotations
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.api.v1.improvement_reports import (
    admin_get_report,
    admin_list_reports,
    admin_patch_report,
    check_report_exists,
    create_improvement_report,
)
from app.models.generation_record import GenerationRecord
from app.models.improvement_report import ImprovementReport
from app.models.user import User
from app.schemas.improvement_report import (
    ImprovementReportCreate,
    ImprovementReportPatch,
    ReportCategoryEnum,
    ReportStatusEnum,
    is_legal_transition,
)


# ── helpers ──────────────────────────────────────────────────────

def _make_user(uid: str = "user-1", role: str = "user", username: str = "alice") -> User:
    u = MagicMock(spec=User)
    u.id = uid
    u.role = role
    u.username = username
    return u


def _make_record(rid: str, *, user_id: str = "user-1", template_id: str | None = "sva_xyz",
                 generation_mode: str = "rag", output_code: str = "// code") -> GenerationRecord:
    r = GenerationRecord(
        id=rid,
        user_id=user_id,
        original_intent=f"intent for {rid}",
        cache_hit=False,
        intent_cache_hit=False,
    )
    r.template_id = template_id
    r.output_code = output_code
    r.params_used = {"foo": "bar"}
    r.generation_mode = generation_mode
    return r


def _make_db_with_records(records: dict[str, GenerationRecord | None]):
    """`db.get(GenerationRecord, id)` 返预设。create/commit/rollback/refresh 都是 awaitable mock。

    db.add 模拟 SQLAlchemy flush 阶段对 ORM 默认 id 的回填，让 endpoint 内的
    `ImprovementReportCreated(id=report.id, ...)` 校验通过。
    """
    db = MagicMock()

    async def _get(model, id_):
        return records.get(id_)

    def _add(obj):
        # SQLAlchemy 真实行为：flush 时 default=lambda 才触发；mock 测试里
        # 没有真 flush，需要手动模拟。
        if getattr(obj, "id", None) is None:
            import uuid
            obj.id = str(uuid.uuid4())

    db.get = AsyncMock(side_effect=_get)
    db.add = MagicMock(side_effect=_add)
    db.commit = AsyncMock(return_value=None)
    db.rollback = AsyncMock(return_value=None)
    db.refresh = AsyncMock(return_value=None)
    db.execute = AsyncMock()
    return db


# ── ReportCategoryEnum 契约 ────────────────────────────────────

def test_report_category_enum_slug_values():
    """spec §5：4 slug 与前端 / ARCH §4.1.4 双向对照。"""
    assert ReportCategoryEnum.WRONG_TEMPLATE.value == "wrong_template"
    assert ReportCategoryEnum.WRONG_PARAMS.value == "wrong_params"
    assert ReportCategoryEnum.POOR_STYLE.value == "poor_style"
    assert ReportCategoryEnum.OTHER.value == "other"


def test_create_payload_all_optional_fields_empty_ok():
    """spec §2 AC1：categories 与 reporter_note 均不填仍合法。"""
    payload = ImprovementReportCreate(
        rag_record_id="rag-1",
        llm_direct_record_id="llm-1",
    )
    assert payload.report_categories is None
    assert payload.reporter_note is None


# ── 状态机契约 ────────────────────────────────────────────────

@pytest.mark.parametrize(
    "current,target,legal",
    [
        ("pending", "in_review", True),
        ("in_review", "resolved", True),
        ("pending", "resolved", False),  # 跳过 in_review
        ("resolved", "pending", False),  # 回退
        ("resolved", "in_review", False),  # 回退
        ("in_review", "pending", False),  # 回退
        ("pending", "pending", True),  # 同状态（仅改 admin_note）合法
        ("resolved", "resolved", True),
    ],
)
def test_state_machine_transitions(current, target, legal):
    assert is_legal_transition(current, target) is legal


# ── POST /improvement-reports ───────────────────────────────────

@pytest.mark.asyncio
async def test_create_happy_path_categories_and_note_empty_returns_201_pending():
    rag = _make_record("rag-1")
    llm = _make_record("llm-1", generation_mode="llm_direct", template_id=None)
    db = _make_db_with_records({"rag-1": rag, "llm-1": llm})
    payload = ImprovementReportCreate(rag_record_id="rag-1", llm_direct_record_id="llm-1")
    user = _make_user()

    resp = await create_improvement_report(payload, db=db, current_user=user)

    db.add.assert_called_once()
    added = db.add.call_args.args[0]
    assert isinstance(added, ImprovementReport)
    assert added.rag_record_id == "rag-1"
    assert added.llm_direct_record_id == "llm-1"
    assert added.reporter_user_id == user.id
    assert added.status == "pending"
    assert added.report_categories is None  # 空列表也不应写入
    assert added.reporter_note is None
    db.commit.assert_awaited_once()
    assert resp.status == ReportStatusEnum.PENDING


@pytest.mark.asyncio
async def test_create_with_categories_serializes_to_slug_list():
    rag = _make_record("rag-1")
    llm = _make_record("llm-1")
    db = _make_db_with_records({"rag-1": rag, "llm-1": llm})
    payload = ImprovementReportCreate(
        rag_record_id="rag-1",
        llm_direct_record_id="llm-1",
        report_categories=[ReportCategoryEnum.WRONG_TEMPLATE, ReportCategoryEnum.POOR_STYLE],
        reporter_note="试一下",
    )
    await create_improvement_report(payload, db=db, current_user=_make_user())
    added = db.add.call_args.args[0]
    assert added.report_categories == ["wrong_template", "poor_style"]
    assert added.reporter_note == "试一下"


@pytest.mark.asyncio
async def test_create_missing_rag_fk_returns_422_invalid_record_ref():
    db = _make_db_with_records({"rag-1": None, "llm-1": _make_record("llm-1")})
    payload = ImprovementReportCreate(rag_record_id="rag-1", llm_direct_record_id="llm-1")
    with pytest.raises(HTTPException) as exc:
        await create_improvement_report(payload, db=db, current_user=_make_user())
    assert exc.value.status_code == 422
    assert exc.value.detail["type"] == "invalid_record_ref"
    db.add.assert_not_called()
    db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_create_missing_llm_fk_returns_422_invalid_record_ref():
    db = _make_db_with_records({"rag-1": _make_record("rag-1"), "llm-1": None})
    payload = ImprovementReportCreate(rag_record_id="rag-1", llm_direct_record_id="llm-1")
    with pytest.raises(HTTPException) as exc:
        await create_improvement_report(payload, db=db, current_user=_make_user())
    assert exc.value.status_code == 422
    assert exc.value.detail["type"] == "invalid_record_ref"


@pytest.mark.asyncio
async def test_create_duplicate_pair_returns_409_with_existing_report_id():
    """spec §2 AC2：同对重复提交 → 409 + detail.existing_report_id。"""
    rag = _make_record("rag-1")
    llm = _make_record("llm-1")
    db = _make_db_with_records({"rag-1": rag, "llm-1": llm})
    db.commit = AsyncMock(side_effect=IntegrityError("dup", {}, Exception("unique violation")))

    # rollback 后的 SELECT 返已存在的报告
    existing_report = ImprovementReport(
        id="existing-1",
        rag_record_id="rag-1",
        llm_direct_record_id="llm-1",
        reporter_user_id="user-prev",
        status="pending",
    )
    scalar_mock = MagicMock()
    scalar_mock.scalar_one_or_none = MagicMock(return_value=existing_report)
    db.execute = AsyncMock(return_value=scalar_mock)

    payload = ImprovementReportCreate(rag_record_id="rag-1", llm_direct_record_id="llm-1")
    with pytest.raises(HTTPException) as exc:
        await create_improvement_report(payload, db=db, current_user=_make_user())
    assert exc.value.status_code == 409
    assert exc.value.detail["type"] == "duplicate_report"
    assert exc.value.detail["existing_report_id"] == "existing-1"
    db.rollback.assert_awaited_once()


# ── GET /improvement-reports/check ────────────────────────────────

@pytest.mark.asyncio
async def test_check_returns_exists_true_with_report_id():
    # 归属权门：必须把 record 设为属于 current_user（user-1）才能查询
    rag = _make_record("rag-1", user_id="user-1")
    llm = _make_record("llm-1", user_id="user-1")
    db = _make_db_with_records({"rag-1": rag, "llm-1": llm})
    scalar_mock = MagicMock()
    scalar_mock.scalar_one_or_none = MagicMock(return_value="report-xyz")
    db.execute = AsyncMock(return_value=scalar_mock)

    resp = await check_report_exists("rag-1", "llm-1", db=db, current_user=_make_user())
    assert resp.exists is True
    assert resp.report_id == "report-xyz"


@pytest.mark.asyncio
async def test_check_returns_exists_false_when_no_report():
    rag = _make_record("rag-1", user_id="user-1")
    llm = _make_record("llm-1", user_id="user-1")
    db = _make_db_with_records({"rag-1": rag, "llm-1": llm})
    scalar_mock = MagicMock()
    scalar_mock.scalar_one_or_none = MagicMock(return_value=None)
    db.execute = AsyncMock(return_value=scalar_mock)

    resp = await check_report_exists("rag-1", "llm-1", db=db, current_user=_make_user())
    assert resp.exists is False
    assert resp.report_id is None


# ── PATCH /admin/improvement-reports/{id} 状态机 ──────────────────

def _make_report(rid: str = "rep-1", status: str = "pending") -> ImprovementReport:
    r = ImprovementReport(
        id=rid,
        rag_record_id="rag-1",
        llm_direct_record_id="llm-1",
        reporter_user_id="user-1",
        status=status,
        report_categories=None,
        reporter_note=None,
        admin_note=None,
    )
    r.created_at = datetime.now(timezone.utc)
    r.updated_at = datetime.now(timezone.utc)
    return r


def _admin_db_for_patch(report: ImprovementReport, rag: GenerationRecord | None = None,
                        llm: GenerationRecord | None = None, reporter: User | None = None):
    """admin_get_report 末尾会再 db.get(User) + db.get(GenerationRecord) 拉详情；模拟之。"""
    rag = rag or _make_record("rag-1")
    llm = llm or _make_record("llm-1")
    reporter = reporter or _make_user(uid=report.reporter_user_id, username="alice")

    objects = {
        ("ImprovementReport", report.id): report,
        ("GenerationRecord", "rag-1"): rag,
        ("GenerationRecord", "llm-1"): llm,
        ("User", report.reporter_user_id): reporter,
    }

    async def _get(model, id_):
        return objects.get((model.__name__, id_))

    db = MagicMock()
    db.get = AsyncMock(side_effect=_get)
    db.commit = AsyncMock(return_value=None)
    db.refresh = AsyncMock(return_value=None)

    # admin_get_report 内的 templates 查询返回空——template_name 走 None 分支
    empty_rows = MagicMock()
    empty_rows.all = MagicMock(return_value=[])
    db.execute = AsyncMock(return_value=empty_rows)
    return db


@pytest.mark.asyncio
async def test_patch_pending_to_in_review_ok():
    report = _make_report(status="pending")
    db = _admin_db_for_patch(report)
    admin = _make_user(uid="admin-1", role="lib_admin", username="bob")
    payload = ImprovementReportPatch(status=ReportStatusEnum.IN_REVIEW)

    resp = await admin_patch_report(report.id, payload, db=db, current_user=admin)
    assert resp.status == ReportStatusEnum.IN_REVIEW
    assert report.status == "in_review"
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_patch_in_review_to_resolved_ok():
    report = _make_report(status="in_review")
    db = _admin_db_for_patch(report)
    admin = _make_user(uid="admin-1", role="lib_admin")
    payload = ImprovementReportPatch(
        status=ReportStatusEnum.RESOLVED,
        admin_note="已批改语料",
    )
    resp = await admin_patch_report(report.id, payload, db=db, current_user=admin)
    assert resp.status == ReportStatusEnum.RESOLVED
    assert report.admin_note == "已批改语料"


@pytest.mark.asyncio
async def test_patch_pending_to_resolved_skip_in_review_returns_422():
    report = _make_report(status="pending")
    db = _admin_db_for_patch(report)
    admin = _make_user(uid="admin-1", role="lib_admin")
    payload = ImprovementReportPatch(status=ReportStatusEnum.RESOLVED)
    with pytest.raises(HTTPException) as exc:
        await admin_patch_report(report.id, payload, db=db, current_user=admin)
    assert exc.value.status_code == 422
    assert exc.value.detail["type"] == "illegal_status_transition"
    assert report.status == "pending"  # 未修改
    db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_patch_resolved_back_to_pending_returns_422():
    report = _make_report(status="resolved")
    db = _admin_db_for_patch(report)
    admin = _make_user(uid="admin-1", role="lib_admin")
    payload = ImprovementReportPatch(status=ReportStatusEnum.PENDING)
    with pytest.raises(HTTPException) as exc:
        await admin_patch_report(report.id, payload, db=db, current_user=admin)
    assert exc.value.status_code == 422
    assert exc.value.detail["type"] == "illegal_status_transition"


@pytest.mark.asyncio
async def test_patch_admin_note_only_does_not_change_status():
    """单独传 admin_note（不带 status）允许任何当前状态下更新。"""
    report = _make_report(status="resolved")  # 已 resolved 仍可改 note
    db = _admin_db_for_patch(report)
    admin = _make_user(uid="admin-1", role="lib_admin")
    payload = ImprovementReportPatch(admin_note="新增审阅笔记")
    resp = await admin_patch_report(report.id, payload, db=db, current_user=admin)
    assert resp.status == ReportStatusEnum.RESOLVED
    assert report.admin_note == "新增审阅笔记"


@pytest.mark.asyncio
async def test_patch_not_found_returns_404():
    db = _admin_db_for_patch(_make_report())
    # 覆写 db.get 返 None for ImprovementReport
    async def _get(model, id_):
        if model.__name__ == "ImprovementReport":
            return None
        return None
    db.get = AsyncMock(side_effect=_get)
    admin = _make_user(uid="admin-1", role="lib_admin")
    payload = ImprovementReportPatch(status=ReportStatusEnum.IN_REVIEW)
    with pytest.raises(HTTPException) as exc:
        await admin_patch_report("missing", payload, db=db, current_user=admin)
    assert exc.value.status_code == 404


# ── GET /admin/improvement-reports/{id} ──────────────────────────

@pytest.mark.asyncio
async def test_admin_get_report_returns_three_column_detail():
    report = _make_report(status="in_review")
    rag = _make_record("rag-1", template_id="sva_handshake_v1", output_code="// rag code")
    llm = _make_record("llm-1", template_id=None, generation_mode="llm_direct",
                       output_code="// llm freeform code")
    reporter = _make_user(uid=report.reporter_user_id, username="alice")
    db = _admin_db_for_patch(report, rag=rag, llm=llm, reporter=reporter)

    # templates 表查询返 (id, name) 元组列表
    template_rows = MagicMock()
    template_rows.all = MagicMock(return_value=[("sva_handshake_v1", "AXI Handshake")])
    db.execute = AsyncMock(return_value=template_rows)

    admin = _make_user(uid="admin-1", role="lib_admin")
    resp = await admin_get_report(report.id, db=db, current_user=admin)
    assert resp.id == report.id
    assert resp.status == ReportStatusEnum.IN_REVIEW
    assert resp.reporter_username == "alice"
    assert resp.rag_record.template_name == "AXI Handshake"
    assert resp.rag_record.output_code == "// rag code"
    assert resp.llm_direct_record.template_name is None  # llm_direct 无 template
    assert resp.llm_direct_record.output_code == "// llm freeform code"


@pytest.mark.asyncio
async def test_admin_get_report_404_when_missing():
    db = _admin_db_for_patch(_make_report())
    async def _get(model, id_):
        return None
    db.get = AsyncMock(side_effect=_get)
    admin = _make_user(uid="admin-1", role="lib_admin")
    with pytest.raises(HTTPException) as exc:
        await admin_get_report("missing", db=db, current_user=admin)
    assert exc.value.status_code == 404


# ── GET /admin/improvement-reports（分页 / filter）────────────────

@pytest.mark.asyncio
async def test_admin_list_filters_status_and_paginates():
    report1 = _make_report("rep-1", status="pending")
    report2 = _make_report("rep-2", status="pending")
    rows = MagicMock()
    rows.all = MagicMock(return_value=[
        (report1, "alice", "sva_a", "TmplA"),
        (report2, "bob", "sva_b", "TmplB"),
    ])
    db = MagicMock()
    db.execute = AsyncMock(return_value=rows)
    admin = _make_user(uid="admin-1", role="lib_admin")
    resp = await admin_list_reports(
        status=ReportStatusEnum.PENDING,
        categories=None,
        page=1,
        page_size=20,
        db=db,
        current_user=admin,
    )
    assert len(resp) == 2
    assert resp[0].id == "rep-1"
    assert resp[0].rag_template_name == "TmplA"
    assert resp[1].reporter_username == "bob"


@pytest.mark.asyncio
async def test_admin_list_filters_by_categories():
    report1 = _make_report("rep-1", status="in_review")
    report1.report_categories = ["wrong_template"]
    rows = MagicMock()
    rows.all = MagicMock(return_value=[(report1, "alice", "sva_a", "TmplA")])
    db = MagicMock()
    db.execute = AsyncMock(return_value=rows)
    admin = _make_user(uid="admin-1", role="lib_admin")
    resp = await admin_list_reports(
        status=None,
        categories=[ReportCategoryEnum.WRONG_TEMPLATE],
        page=1,
        page_size=20,
        db=db,
        current_user=admin,
    )
    assert len(resp) == 1
    assert resp[0].categories == ["wrong_template"]


@pytest.mark.asyncio
async def test_admin_list_empty_returns_empty_list():
    rows = MagicMock()
    rows.all = MagicMock(return_value=[])
    db = MagicMock()
    db.execute = AsyncMock(return_value=rows)
    admin = _make_user(uid="admin-1", role="lib_admin")
    resp = await admin_list_reports(
        status=None, categories=None, page=1, page_size=20,
        db=db, current_user=admin,
    )
    assert resp == []


# ── 归属权 / 403 安全闸门 (spec §2 AC4 + AC6) ─────────────────────

@pytest.mark.asyncio
async def test_create_403_when_normal_user_targets_other_users_record():
    """spec §2 隐含 + 安全审查 M1：普通用户不能对他人的 record 提交报告。"""
    rag = _make_record("rag-1", user_id="user-owner")
    llm = _make_record("llm-1", user_id="user-owner")
    db = _make_db_with_records({"rag-1": rag, "llm-1": llm})
    attacker = _make_user(uid="user-attacker", role="user")
    payload = ImprovementReportCreate(rag_record_id="rag-1", llm_direct_record_id="llm-1")
    with pytest.raises(HTTPException) as exc:
        await create_improvement_report(payload, db=db, current_user=attacker)
    assert exc.value.status_code == 403
    assert exc.value.detail["type"] == "forbidden_record_ownership"
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_create_admin_can_submit_on_behalf_of_other_user():
    """admin 角色绕过归属权（审核场景）。"""
    rag = _make_record("rag-1", user_id="user-owner")
    llm = _make_record("llm-1", user_id="user-owner")
    db = _make_db_with_records({"rag-1": rag, "llm-1": llm})
    admin = _make_user(uid="admin-1", role="lib_admin")
    payload = ImprovementReportCreate(rag_record_id="rag-1", llm_direct_record_id="llm-1")
    resp = await create_improvement_report(payload, db=db, current_user=admin)
    db.add.assert_called_once()
    assert resp.status == ReportStatusEnum.PENDING


@pytest.mark.asyncio
async def test_check_other_users_record_returns_exists_false_no_leak():
    """探测他人 record 永远返 exists=false——不泄露 DB 中是否存在该 record 或 report。"""
    rag = _make_record("rag-1", user_id="user-owner")
    llm = _make_record("llm-1", user_id="user-owner")
    db = _make_db_with_records({"rag-1": rag, "llm-1": llm})
    attacker = _make_user(uid="user-attacker", role="user")
    resp = await check_report_exists("rag-1", "llm-1", db=db, current_user=attacker)
    assert resp.exists is False
    assert resp.report_id is None


# ── require_role 闸门：普通用户访问 admin 路由返 403 (spec §2 AC6) ──

@pytest.mark.asyncio
async def test_require_role_blocks_normal_user_on_admin_route():
    """spec §2 AC6：普通用户访问 admin 路由 → require_role 抛 HTTPException 403。

    这是 GET /admin/improvement-reports / GET /admin/improvement-reports/{id} /
    PATCH /admin/improvement-reports/{id} 三条路由共享的鉴权闸门。直接调
    require_role 工厂返回的 dependency 函数，传普通用户即返 403。
    """
    from app.core.security import require_role

    guard = require_role("lib_admin", "super_admin")
    normal_user = _make_user(uid="user-1", role="user")
    with pytest.raises(HTTPException) as exc:
        await guard(current_user=normal_user)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_require_role_allows_lib_admin():
    from app.core.security import require_role

    guard = require_role("lib_admin", "super_admin")
    admin = _make_user(uid="admin-1", role="lib_admin")
    result = await guard(current_user=admin)
    assert result.role == "lib_admin"


@pytest.mark.asyncio
async def test_require_role_allows_super_admin():
    from app.core.security import require_role

    guard = require_role("lib_admin", "super_admin")
    admin = _make_user(uid="root", role="super_admin")
    result = await guard(current_user=admin)
    assert result.role == "super_admin"


# ── happy-path response carries id (spec §2 AC1 完整断言) ──────────

@pytest.mark.asyncio
async def test_create_response_carries_non_empty_id():
    """spec §2 AC1 末句 'response carries id'：补强对 resp.id 的断言。"""
    rag = _make_record("rag-1")
    llm = _make_record("llm-1")
    db = _make_db_with_records({"rag-1": rag, "llm-1": llm})
    payload = ImprovementReportCreate(rag_record_id="rag-1", llm_direct_record_id="llm-1")
    resp = await create_improvement_report(payload, db=db, current_user=_make_user())
    assert resp.id is not None
    assert len(resp.id) > 0
