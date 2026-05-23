"""Add template_corpus_cases table for Layer 3a/3b regression corpus

每条记录代表"intent X 应命中 template Y"的契约，供 pre-approve-analysis 冲突检测
和后续持续回归使用。

Revision ID: 005
Revises: 004
Create Date: 2026-05-23 00:00:00.000000
"""
from __future__ import annotations
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "template_corpus_cases",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("intent", sa.Text(), nullable=False),
        sa.Column("code_type", sa.String(16), nullable=False),
        sa.Column(
            "expected_template_id",
            sa.String(32),
            sa.ForeignKey("templates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source", sa.String(32), nullable=False, server_default="auto_generated"),
        sa.Column(
            "auto_generated_from",
            sa.String(36),
            sa.ForeignKey("template_contributions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index(
        "ix_template_corpus_cases_template",
        "template_corpus_cases",
        ["expected_template_id"],
    )
    op.create_index(
        "ix_template_corpus_cases_active",
        "template_corpus_cases",
        ["is_active"],
        postgresql_where=sa.text("is_active = true"),
    )


def downgrade() -> None:
    op.drop_index("ix_template_corpus_cases_active", table_name="template_corpus_cases")
    op.drop_index("ix_template_corpus_cases_template", table_name="template_corpus_cases")
    op.drop_table("template_corpus_cases")
