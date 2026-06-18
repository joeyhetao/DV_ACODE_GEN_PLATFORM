"""Add feedback + generation_mode + gate_error_type columns to generation_records.

L3 用户反馈机制 + L4 管理员分析仪表盘的数据基础设施：
- feedback_rating / feedback_reason_tags / feedback_comment / feedback_at：
    用户对生成结果的 3 档评分（1=好 / 2=一般 / 3=差）+ 差评 reason tags + 自由文本。
- generation_mode：代码来源（'rag' 走 RAG+模板渲染；'llm_direct' 为 L2 直接 LLM 预留）。
- gate_error_type：5 道闸触发记录（'no_matching_template' / 'off_topic' /
    'under_specified' / 'code_type_mismatch' / 'empty_retrieval'）；analytics
    no-match-rate 端点的数据源。

Revision ID: 006
Revises: 005
Create Date: 2026-05-29 00:00:00.000000
"""
from __future__ import annotations
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "generation_records",
        sa.Column("feedback_rating", sa.SmallInteger(), nullable=True),
    )
    op.add_column(
        "generation_records",
        sa.Column("feedback_reason_tags", JSONB(), nullable=True),
    )
    op.add_column(
        "generation_records",
        sa.Column("feedback_comment", sa.Text(), nullable=True),
    )
    op.add_column(
        "generation_records",
        sa.Column("feedback_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "generation_records",
        sa.Column(
            "generation_mode",
            sa.String(16),
            nullable=True,
            server_default="rag",
        ),
    )
    op.add_column(
        "generation_records",
        sa.Column("gate_error_type", sa.String(32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("generation_records", "gate_error_type")
    op.drop_column("generation_records", "generation_mode")
    op.drop_column("generation_records", "feedback_at")
    op.drop_column("generation_records", "feedback_comment")
    op.drop_column("generation_records", "feedback_reason_tags")
    op.drop_column("generation_records", "feedback_rating")
