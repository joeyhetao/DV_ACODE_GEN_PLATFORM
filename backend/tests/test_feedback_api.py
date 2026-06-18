"""L3 用户反馈端点单测：

- FeedbackCreate Pydantic 校验：rating ∈ {0, 4, 99} 触发 422 校验错误
- FeedbackCreate 跨字段：rating=3 且 reason_tags 为空 → 422
- submit_feedback handler：
    * generation_record_id 不存在 → 404
    * record.user_id != current_user.id 且 current_user.role 非 admin → 403
    * 合法请求 → 204 + 5 列写入（rating / reason_tags / comment / feedback_at / generation_mode）

跑法（容器内）:
    docker compose exec backend pytest tests/test_feedback_api.py -v

测试不依赖 live PG / Redis / LLM。AsyncSession 用 unittest.mock 桩。
"""
from __future__ import annotations
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.v1.feedback import submit_feedback
from app.models.generation_record import GenerationRecord
from app.models.user import User
from app.schemas.feedback import FeedbackCreate, ReasonTagEnum


# ── Pydantic 校验 ─────────────────────────────────────────────────────

@pytest.mark.parametrize("bad_rating", [0, 4, 5, 99, -1])
def test_feedback_create_rating_out_of_range_raises_422(bad_rating: int):
    with pytest.raises(ValidationError):
        FeedbackCreate(rating=bad_rating)


def test_feedback_create_rating_3_without_reason_tags_raises():
    with pytest.raises(ValidationError) as exc_info:
        FeedbackCreate(rating=3, reason_tags=None, comment="bad output")
    msg = str(exc_info.value)
    assert "reason_tags" in msg


def test_feedback_create_rating_3_with_empty_reason_tags_raises():
    with pytest.raises(ValidationError):
        FeedbackCreate(rating=3, reason_tags=[], comment="bad")


def test_feedback_create_rating_1_or_2_allows_empty_reason_tags():
    FeedbackCreate(rating=1)
    FeedbackCreate(rating=2, comment="acceptable")


def test_feedback_create_rating_3_with_valid_tag_passes():
    payload = FeedbackCreate(
        rating=3,
        reason_tags=[ReasonTagEnum.WRONG_TEMPLATE, ReasonTagEnum.HALLUCINATED_SIGNAL],
        comment="wrong template + fake signal",
    )
    assert payload.rating == 3
    assert payload.reason_tags == [
        ReasonTagEnum.WRONG_TEMPLATE,
        ReasonTagEnum.HALLUCINATED_SIGNAL,
    ]


def test_feedback_create_invalid_reason_tag_value_raises():
    with pytest.raises(ValidationError):
        FeedbackCreate(rating=3, reason_tags=["definitely_not_a_valid_tag"])


# ── Handler 行为 ─────────────────────────────────────────────────────

def _make_user(uid: str = "user-self", role: str = "user") -> User:
    u = MagicMock(spec=User)
    u.id = uid
    u.role = role
    return u


def _make_record(uid: str = "user-self") -> GenerationRecord:
    r = GenerationRecord(
        id="rec-1",
        user_id=uid,
        original_intent="foo",
        cache_hit=False,
        intent_cache_hit=False,
    )
    return r


def _make_db(record: GenerationRecord | None) -> MagicMock:
    db = MagicMock()
    db.get = AsyncMock(return_value=record)
    db.commit = AsyncMock(return_value=None)
    return db


@pytest.mark.asyncio
async def test_submit_feedback_record_not_found_404():
    db = _make_db(None)
    user = _make_user()
    payload = FeedbackCreate(rating=1)
    with pytest.raises(HTTPException) as exc_info:
        await submit_feedback("missing-id", payload, db=db, current_user=user)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_submit_feedback_other_users_record_403_for_normal_user():
    record = _make_record(uid="user-owner")
    db = _make_db(record)
    other = _make_user(uid="user-attacker", role="user")
    payload = FeedbackCreate(rating=1)
    with pytest.raises(HTTPException) as exc_info:
        await submit_feedback("rec-1", payload, db=db, current_user=other)
    assert exc_info.value.status_code == 403
    # 校验没有写入任何字段
    assert record.feedback_rating is None
    assert record.feedback_at is None


@pytest.mark.asyncio
async def test_submit_feedback_admin_can_submit_for_other_user():
    record = _make_record(uid="user-owner")
    db = _make_db(record)
    admin = _make_user(uid="admin-1", role="lib_admin")
    payload = FeedbackCreate(rating=1, comment="post-hoc audit")
    resp = await submit_feedback("rec-1", payload, db=db, current_user=admin)
    assert resp.status_code == 204
    assert record.feedback_rating == 1
    assert record.feedback_comment == "post-hoc audit"
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_submit_feedback_super_admin_can_submit_for_other_user():
    record = _make_record(uid="user-owner")
    db = _make_db(record)
    admin = _make_user(uid="root", role="super_admin")
    payload = FeedbackCreate(rating=2)
    resp = await submit_feedback("rec-1", payload, db=db, current_user=admin)
    assert resp.status_code == 204
    assert record.feedback_rating == 2


@pytest.mark.asyncio
async def test_submit_feedback_owner_good_rating_writes_5_columns():
    record = _make_record(uid="user-self")
    db = _make_db(record)
    user = _make_user()
    payload = FeedbackCreate(rating=1, comment="looks good")
    before = datetime.now(timezone.utc)
    resp = await submit_feedback("rec-1", payload, db=db, current_user=user)
    after = datetime.now(timezone.utc)
    assert resp.status_code == 204
    assert record.feedback_rating == 1
    assert record.feedback_reason_tags is None
    assert record.feedback_comment == "looks good"
    assert record.feedback_at is not None
    assert before <= record.feedback_at <= after
    assert record.generation_mode == "rag"
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_submit_feedback_owner_bad_rating_serializes_reason_tags():
    record = _make_record(uid="user-self")
    db = _make_db(record)
    user = _make_user()
    payload = FeedbackCreate(
        rating=3,
        reason_tags=[ReasonTagEnum.SYNTAX_ERROR, ReasonTagEnum.MISSING_DISABLE_IFF],
        comment="syntax + missing disable iff",
    )
    resp = await submit_feedback("rec-1", payload, db=db, current_user=user)
    assert resp.status_code == 204
    assert record.feedback_rating == 3
    # 验证 enum 序列化为字符串列表（JSONB 存储）
    assert record.feedback_reason_tags == ["syntax_error", "missing_disable_iff"]
    assert record.feedback_comment == "syntax + missing disable iff"


@pytest.mark.asyncio
async def test_submit_feedback_preserves_existing_generation_mode():
    """spec：如果 record 已有 generation_mode，不应覆盖。"""
    record = _make_record(uid="user-self")
    record.generation_mode = "llm_direct"
    db = _make_db(record)
    user = _make_user()
    payload = FeedbackCreate(rating=1)
    await submit_feedback("rec-1", payload, db=db, current_user=user)
    assert record.generation_mode == "llm_direct"
