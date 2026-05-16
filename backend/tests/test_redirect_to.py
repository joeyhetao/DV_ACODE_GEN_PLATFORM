"""v3.0 redirect_to 字段单测：验证 4 个错误类的 detail 生成器是否正确填值。

主路径：UnderSpecifiedIntentError → detail.redirect_to 含 /intent-builder?prefill=...
其他 3 闸：detail.redirect_to=None（前端在原页面 fallback Modal）

跑法：docker compose exec backend pytest tests/test_redirect_to.py -v
"""
from urllib.parse import parse_qs, urlparse

from app.api.v1.generate import (
    _off_topic_detail,
    _code_type_mismatch_detail,
    _empty_retrieval_detail,
    _under_specified_detail,
)
from app.services.core.pipeline import (
    OffTopicIntentError,
    CodeTypeMismatchError,
    EmptyRetrievalError,
    UnderSpecifiedIntentError,
)


def test_off_topic_detail_redirect_to_is_null():
    """off-topic 不带 redirect_to——IntentBuilder 救不了真离题。"""
    e = OffTopicIntentError(top_dense_score=0.2, threshold=0.44)
    d = _off_topic_detail(e)
    assert d["type"] == "off_topic"
    assert d["redirect_to"] is None


def test_code_type_mismatch_detail_redirect_to_is_null():
    """code_type 错配不带 redirect_to——前端在原页面弹 Modal 让用户切 code_type。"""
    e = CodeTypeMismatchError(
        selected_code_type="assertion",
        suggested_code_type="coverage",
        selected_score=0.62,
        suggested_score=0.76,
    )
    d = _code_type_mismatch_detail(e)
    assert d["type"] == "code_type_mismatch"
    assert d["redirect_to"] is None


def test_empty_retrieval_detail_redirect_to_is_null():
    """empty_retrieval 503 基础设施异常——跳哪都救不了，redirect_to=None。"""
    e = EmptyRetrievalError(code_type="assertion")
    d = _empty_retrieval_detail(e)
    assert d["type"] == "empty_retrieval"
    assert d["redirect_to"] is None


def test_under_specified_detail_redirect_to_points_to_intent_builder():
    """under_specified 带 redirect_to=/intent-builder?prefill=...&template_id=...&missing=...

    前端 handleApiError 读到后 router.push，进入对话精修。
    """
    e = UnderSpecifiedIntentError(
        template_id="cov_transition_coverage_v1",
        template_name="状态转换覆盖率组",
        missing_params=[
            {"name": "signal", "description": "被覆盖信号名"},
            {"name": "state_list", "description": "合法状态值列表"},
        ],
        original_intent="生成一个 FSM 转换覆盖率",
        code_type="coverage",
    )
    d = _under_specified_detail(e)
    assert d["type"] == "under_specified"
    assert d["redirect_to"] is not None
    parsed = urlparse(d["redirect_to"])
    assert parsed.path == "/intent-builder"
    q = parse_qs(parsed.query)
    assert q["template_id"] == ["cov_transition_coverage_v1"]
    assert q["code_type"] == ["coverage"]
    assert q["prefill"] == ["生成一个 FSM 转换覆盖率"]
    assert q["missing"] == ["signal,state_list"]


def test_under_specified_detail_quotes_special_chars_in_intent():
    """中文 + 特殊字符的 intent 应该被 URL 编码。"""
    e = UnderSpecifiedIntentError(
        template_id="sva_x",
        template_name="X",
        missing_params=[{"name": "signal", "description": ""}],
        original_intent="对 a&b=1 做断言",
        code_type="assertion",
    )
    d = _under_specified_detail(e)
    # 直接验证 URL 串不含未编码的 & = 在 prefill 段（除了作为分隔符）
    parsed = urlparse(d["redirect_to"])
    q = parse_qs(parsed.query)
    assert q["prefill"] == ["对 a&b=1 做断言"]  # parse_qs 自动解码后能还原


def test_under_specified_without_intent_still_builds_url():
    """original_intent 为空时 URL 不应该有 prefill 段（向后兼容），但 code_type 必填。"""
    e = UnderSpecifiedIntentError(
        template_id="t1",
        template_name="t1",
        missing_params=[{"name": "a", "description": ""}],
        original_intent="",
        code_type="assertion",
    )
    d = _under_specified_detail(e)
    parsed = urlparse(d["redirect_to"])
    q = parse_qs(parsed.query)
    assert "prefill" not in q
    assert q["template_id"] == ["t1"]
    assert q["code_type"] == ["assertion"]


import pytest


def test_under_specified_requires_non_empty_code_type():
    """P1-13：code_type 为空时构造异常应直接 ValueError——防 IntentBuilder 默认 'assertion' 错配。"""
    with pytest.raises(ValueError, match="code_type"):
        UnderSpecifiedIntentError(
            template_id="t1",
            template_name="t1",
            missing_params=[{"name": "a", "description": ""}],
            original_intent="x",
            code_type="",
        )
