"""L3 用户反馈 schema：3 档评分 + 差评 reason tags + 自由文本。

rating 取值约定：1=好 / 2=一般 / 3=差。rating=3 时 reason_tags 必填，
其他档可选。所有评分均允许 comment（自由文本反馈）。
"""
from __future__ import annotations
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, model_validator
from pydantic_core import PydanticCustomError


class ReasonTagEnum(str, Enum):
    """差评原因标签（Stage 1 固定 7 项；新增需 migration + 前端同步）。"""
    WRONG_TEMPLATE = "wrong_template"
    HALLUCINATED_SIGNAL = "hallucinated_signal"
    SYNTAX_ERROR = "syntax_error"
    SEMANTIC_ERROR = "semantic_error"
    STYLE_BAD = "style_bad"
    MISSING_DISABLE_IFF = "missing_disable_iff"
    OTHER = "other"


class FeedbackCreate(BaseModel):
    """POST /feedback/{generation_record_id} 请求体。

    跨字段校验：rating==3 且 reason_tags 为空 → 422，强制差评必填标签
    （否则差评对模板优化无价值）。其他评分允许 reason_tags 为空。
    """
    rating: Literal[1, 2, 3] = Field(
        ...,
        description="1=好 / 2=一般 / 3=差；其他整数返回 422 校验错误",
    )
    reason_tags: list[ReasonTagEnum] | None = Field(
        default=None,
        description="差评必填；其他档可选",
    )
    comment: str | None = Field(
        default=None,
        max_length=2048,
        description="自由文本反馈，所有评分均可选填",
    )

    @model_validator(mode="after")
    def _require_reason_tags_for_bad_rating(self) -> "FeedbackCreate":
        if self.rating == 3 and not self.reason_tags:
            # 用 PydanticCustomError：`type` 字段=reason_tags_required，`msg` 含字段名
            # 让前端从 422 detail 解析。注意：model_validator 抛出的错误 loc 为 ()
            # （Pydantic v2 既定行为，PydanticCustomError 不会改写 loc），前端不应依赖
            # loc 做字段定位，应从 msg 字符串里匹配 reason_tags / type 字段做分支。
            raise PydanticCustomError(
                "reason_tags_required",
                "reason_tags 字段必填：差评（rating=3）时必须至少选择一个原因标签",
            )
        return self
