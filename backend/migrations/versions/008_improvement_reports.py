"""Add improvement_reports table (FEAT-12 用户对比报告系统).

记录用户对 RAG vs LLM 直接生成结果对比的一键报告。三态状态机
pending → in_review → resolved；非法跳转由 API 层 422 兜底。
一对 (rag_record_id, llm_direct_record_id) 仅允许一份对比报告
（UNIQUE 约束）。FK ondelete=CASCADE：generation_record 或
reporter user 被删时，对应报告自动清理（与现有 generation_records
回链策略对齐）。

Revision ID: 008
Revises: 007
Create Date: 2026-06-02 00:00:00.000000
"""
from __future__ import annotations
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 幂等保护：若残留旧 ENUM type 重跑会失败。手写 DO $$ 块用 IF NOT EXISTS 兜底。
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'report_status_enum') THEN
                CREATE TYPE report_status_enum AS ENUM ('pending', 'in_review', 'resolved');
            END IF;
        END$$;
        """
    )

    op.create_table(
        "improvement_reports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "rag_record_id",
            sa.String(36),
            sa.ForeignKey("generation_records.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "llm_direct_record_id",
            sa.String(36),
            sa.ForeignKey("generation_records.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "reporter_user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("report_categories", postgresql.JSONB(), nullable=True),
        sa.Column("reporter_note", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "in_review",
                "resolved",
                name="report_status_enum",
                create_type=False,
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("admin_note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.UniqueConstraint(
            "rag_record_id",
            "llm_direct_record_id",
            name="uq_improvement_reports_pair",
        ),
    )

    # admin 列表分页：status 过滤 + created_at DESC 排序
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_improvement_reports_status_created
        ON improvement_reports (status, created_at DESC)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_improvement_reports_status_created")
    op.drop_table("improvement_reports")
    op.execute("DROP TYPE IF EXISTS report_status_enum")
