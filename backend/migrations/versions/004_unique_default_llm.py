"""Partial unique index: at most one row has is_default=true

应用层在 admin_llm.py 用一次性 UPDATE 把其他行的 is_default 改为 false，但并发
请求 / 事务回滚可能留下多行 True。一旦发生，factory.get_default_llm_client 里的
`scalar_one_or_none()` 会 raise MultipleResultsFound → 500。加 DB 端兜底约束。

Revision ID: 004
Revises: 003
Create Date: 2026-05-14 00:00:00.000000
"""
from __future__ import annotations
from typing import Sequence, Union

from alembic import op


revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ux_llm_configs_one_default
        ON llm_configs (is_default)
        WHERE is_default = true
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ux_llm_configs_one_default")
