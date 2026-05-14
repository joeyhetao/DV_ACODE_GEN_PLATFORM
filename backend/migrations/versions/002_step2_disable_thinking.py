"""Add step2_disable_thinking switch to llm_configs

Revision ID: 002
Revises: 001
Create Date: 2026-05-14 00:00:00.000000
"""
from __future__ import annotations
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "llm_configs",
        sa.Column(
            "step2_disable_thinking",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )


def downgrade() -> None:
    op.drop_column("llm_configs", "step2_disable_thinking")
