"""L4 管理员分析端点单测：

覆盖 4 个端点的 SQL 聚合后处理：
  - /admin/analytics/feedback-summary
  - /admin/analytics/template-issues
  - /admin/analytics/intent-confusion
  - /admin/analytics/no-match-rate

每个端点覆盖：(a) 空数据 → 0 / [] / 0.0；(b) 有数据 → 正确聚合 + 排序。
AsyncSession 用 unittest.mock 桩，db.execute 的 side_effect 按调用顺序返回 result 对象。

跑法（容器内）:
    docker compose exec backend pytest tests/test_admin_analytics.py -v
"""
from __future__ import annotations
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.v1.admin import (
    analytics_feedback_summary,
    analytics_template_issues,
    analytics_intent_confusion,
    analytics_no_match_rate,
)


def _scalar_result(value):
    """模拟 db.execute(...).scalar() 的返回。"""
    r = MagicMock()
    r.scalar = MagicMock(return_value=value)
    return r


def _all_result(rows):
    """模拟 db.execute(...).all() 的返回。"""
    r = MagicMock()
    r.all = MagicMock(return_value=rows)
    return r


def _make_db_with_results(*results):
    """AsyncMock db，execute 按调用顺序返回提供的 result 对象。"""
    db = MagicMock()
    db.execute = AsyncMock(side_effect=list(results))
    return db


def _admin_user():
    u = MagicMock()
    u.id = "admin-1"
    u.role = "lib_admin"
    return u


# ── feedback-summary ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_feedback_summary_empty_returns_zeros():
    """无生成、无反馈：各率应返 0.0，绝不报 500 / NaN。"""
    db = _make_db_with_results(
        _scalar_result(0),  # total_generations
        _scalar_result(0),  # total_feedbacks
        _scalar_result(0),  # bad_feedbacks
        _scalar_result(0),  # no_match_count
    )
    res = await analytics_feedback_summary(days=7, db=db, current_user=_admin_user())
    assert res == {
        "days": 7,
        "total_generations": 0,
        "total_feedbacks": 0,
        "feedback_rate": 0.0,
        "bad_rate": 0.0,
        "no_match_rate": 0.0,
    }


@pytest.mark.asyncio
async def test_feedback_summary_with_data_computes_rates():
    """100 生成 / 40 反馈 / 10 差评 / 8 no-match → feedback_rate=0.4, bad_rate=0.25, no_match_rate=0.08。"""
    db = _make_db_with_results(
        _scalar_result(100),
        _scalar_result(40),
        _scalar_result(10),
        _scalar_result(8),
    )
    res = await analytics_feedback_summary(days=30, db=db, current_user=_admin_user())
    assert res["total_generations"] == 100
    assert res["total_feedbacks"] == 40
    assert res["feedback_rate"] == 0.4
    assert res["bad_rate"] == 0.25
    assert res["no_match_rate"] == 0.08


@pytest.mark.asyncio
async def test_feedback_summary_no_feedback_but_generations_keeps_bad_rate_zero():
    """50 生成、0 反馈：bad_rate 分母为 0 时应返 0.0 而不是 ZeroDivisionError。"""
    db = _make_db_with_results(
        _scalar_result(50),
        _scalar_result(0),
        _scalar_result(0),
        _scalar_result(0),
    )
    res = await analytics_feedback_summary(days=7, db=db, current_user=_admin_user())
    assert res["feedback_rate"] == 0.0
    assert res["bad_rate"] == 0.0


# ── template-issues ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_template_issues_empty_returns_empty_list():
    db = _make_db_with_results(_all_result([]))
    res = await analytics_template_issues(days=7, limit=10, db=db, current_user=_admin_user())
    assert res == []


@pytest.mark.asyncio
async def test_template_issues_sorts_by_bad_rate_desc_then_bad_count_desc():
    rows = [
        SimpleNamespace(template_id="tplA", total_count=10, bad_count=2),
        SimpleNamespace(template_id="tplB", total_count=4, bad_count=2),
        SimpleNamespace(template_id="tplC", total_count=20, bad_count=2),
        SimpleNamespace(template_id="tplD", total_count=8, bad_count=4),
    ]
    db = _make_db_with_results(_all_result(rows))
    res = await analytics_template_issues(days=7, limit=10, db=db, current_user=_admin_user())
    # tplB: 2/4=0.5; tplD: 4/8=0.5; tplA: 2/10=0.2; tplC: 2/20=0.1
    # 0.5 平手 → bad_count 降序：tplD(4) > tplB(2)
    assert [r["template_id"] for r in res] == ["tplD", "tplB", "tplA", "tplC"]
    assert res[0]["bad_rate"] == 0.5
    assert res[0]["bad_count"] == 4


@pytest.mark.asyncio
async def test_template_issues_respects_limit():
    rows = [
        SimpleNamespace(template_id=f"tpl{i}", total_count=10, bad_count=i)
        for i in range(1, 30)
    ]
    db = _make_db_with_results(_all_result(rows))
    res = await analytics_template_issues(days=7, limit=5, db=db, current_user=_admin_user())
    assert len(res) == 5


# ── intent-confusion ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_intent_confusion_empty_returns_empty_list():
    # 空结果走 short-circuit，不查 templates 表 → 只 mock 一次
    db = _make_db_with_results(_all_result([]))
    res = await analytics_intent_confusion(days=7, limit=10, db=db, current_user=_admin_user())
    assert res == []


@pytest.mark.asyncio
async def test_intent_confusion_aggregates_by_template_pair_and_joins_code_type():
    rows = [
        # 期望 tplA 但拿到 tplB —— 出现 3 次（不同 intent 文本仍归同一对模板桶）
        SimpleNamespace(original_intent="intent X1", template_id="tplB",
                        rag_top3=[{"template_id": "tplA", "score": 0.9}]),
        SimpleNamespace(original_intent="intent X2", template_id="tplB",
                        rag_top3=[{"template_id": "tplA", "score": 0.85}]),
        SimpleNamespace(original_intent="intent X3", template_id="tplB",
                        rag_top3=[{"template_id": "tplA", "score": 0.88}]),
        # 期望 tplC 但拿到 tplD —— 出现 1 次
        SimpleNamespace(original_intent="intent Y", template_id="tplD",
                        rag_top3=[{"template_id": "tplC", "score": 0.7}]),
        # RAG top-1 与 actual 相同 —— 不应进入混淆集
        SimpleNamespace(original_intent="intent Z", template_id="tplE",
                        rag_top3=[{"template_id": "tplE", "score": 0.95}]),
        # rag_top3 为空 —— 跳过
        SimpleNamespace(original_intent="intent W", template_id="tplF", rag_top3=[]),
        # rag_top3 顶层不是 dict —— 跳过
        SimpleNamespace(original_intent="intent V", template_id="tplG",
                        rag_top3=["malformed"]),
    ]
    # 第二次 execute 是 templates 表 join，返 (id, code_type) tuple 列表
    type_map_rows = [
        ("tplA", "assertion"),
        ("tplB", "assertion"),
        ("tplC", "functional_coverage"),
        ("tplD", "assertion"),
    ]
    db = _make_db_with_results(_all_result(rows), _all_result(type_map_rows))
    res = await analytics_intent_confusion(days=7, limit=10, db=db, current_user=_admin_user())
    assert len(res) == 2
    # count 降序：(A → B, 3) 排前面，intent 取首条样本 "intent X1"
    assert res[0] == {
        "intent": "intent X1",
        "expected_template": "tplA",
        "actual_template": "tplB",
        "code_type": "assertion",
        "count": 3,
    }
    # actual=tplD → code_type=assertion（actual 优先于 expected）
    assert res[1] == {
        "intent": "intent Y",
        "expected_template": "tplC",
        "actual_template": "tplD",
        "code_type": "assertion",
        "count": 1,
    }


@pytest.mark.asyncio
async def test_intent_confusion_long_intent_is_truncated_to_200_chars():
    long_text = "x" * 500
    rows = [SimpleNamespace(original_intent=long_text, template_id="tplB",
                            rag_top3=[{"template_id": "tplA"}])]
    db = _make_db_with_results(_all_result(rows), _all_result([("tplA", "assertion"), ("tplB", "assertion")]))
    res = await analytics_intent_confusion(days=7, limit=10, db=db, current_user=_admin_user())
    assert len(res[0]["intent"]) == 200


@pytest.mark.asyncio
async def test_intent_confusion_actual_template_missing_falls_back_to_expected_code_type():
    rows = [SimpleNamespace(original_intent="intent", template_id="tplDeleted",
                            rag_top3=[{"template_id": "tplA"}])]
    # tplDeleted 不在 templates 表（被删了），只返 expected 的 code_type
    db = _make_db_with_results(_all_result(rows), _all_result([("tplA", "assertion")]))
    res = await analytics_intent_confusion(days=7, limit=10, db=db, current_user=_admin_user())
    assert res[0]["code_type"] == "assertion"


@pytest.mark.asyncio
async def test_intent_confusion_respects_limit():
    rows = [
        SimpleNamespace(
            original_intent=f"intent {i}",
            template_id="tplActual",
            rag_top3=[{"template_id": f"tplExpected{i}"}],
        )
        for i in range(50)
    ]
    # 50 条都是不同 (expected, actual) 对 → 50 个 bucket，limit=10 截断
    # type_map 只查截断后的 10 条 actual + 10 条 expected = up to 11 unique
    db = _make_db_with_results(_all_result(rows), _all_result([("tplActual", "assertion")]))
    res = await analytics_intent_confusion(days=7, limit=10, db=db, current_user=_admin_user())
    assert len(res) == 10


# ── no-match-rate ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_no_match_rate_empty_returns_empty_list():
    db = _make_db_with_results(_all_result([]))
    res = await analytics_no_match_rate(days=7, db=db, current_user=_admin_user())
    assert res == []


@pytest.mark.asyncio
async def test_no_match_rate_computes_per_day_ratio():
    rows = [
        SimpleNamespace(date=date(2026, 5, 27), total=10, no_match_count=2),
        SimpleNamespace(date=date(2026, 5, 28), total=5, no_match_count=0),
        SimpleNamespace(date=date(2026, 5, 29), total=20, no_match_count=10),
    ]
    db = _make_db_with_results(_all_result(rows))
    res = await analytics_no_match_rate(days=7, db=db, current_user=_admin_user())
    assert res == [
        {"date": "2026-05-27", "total": 10, "no_match_count": 2, "no_match_rate": 0.2},
        {"date": "2026-05-28", "total": 5, "no_match_count": 0, "no_match_rate": 0.0},
        {"date": "2026-05-29", "total": 20, "no_match_count": 10, "no_match_rate": 0.5},
    ]


@pytest.mark.asyncio
async def test_no_match_rate_handles_zero_total_safely():
    """理论上 group_by 不会出现 total=0 的行，但容错：should yield 0.0 instead of ZeroDivisionError。"""
    rows = [SimpleNamespace(date=date(2026, 5, 29), total=0, no_match_count=0)]
    db = _make_db_with_results(_all_result(rows))
    res = await analytics_no_match_rate(days=7, db=db, current_user=_admin_user())
    assert res[0]["no_match_rate"] == 0.0
