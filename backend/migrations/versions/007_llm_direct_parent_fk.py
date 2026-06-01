"""Add parent_record_id FK to generation_records (FEAT-11 Stage 2 llm_direct).

llm_direct 兜底生成（POST /api/v1/generate/llm-fallback）会新建一条
generation_mode='llm_direct' 的 GenerationRecord，并通过 parent_record_id 指向
触发本次 fallback 的源 RAG 记录，让 admin 分析时能把"对 RAG 结果不满意 → 用 LLM
重生成"的链路追溯出来。ondelete=SET NULL：源记录若被删，子记录变孤儿不级联删，
保留 llm_direct 的反馈数据。

Revision ID: 007
Revises: 006
Create Date: 2026-06-01 00:00:00.000000
"""
from __future__ import annotations
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "generation_records",
        sa.Column("parent_record_id", sa.String(36), nullable=True),
    )
    op.create_foreign_key(
        "fk_generation_records_parent_record_id",
        "generation_records",
        "generation_records",
        ["parent_record_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_generation_records_parent_record_id",
        "generation_records",
        type_="foreignkey",
    )
    op.drop_column("generation_records", "parent_record_id")
