"""Align sync_status_enum values with ORM model (idempotent)

migration 001 declared sync_status_enum = ('pending', 'synced', 'error')
but the ORM (app/models/template.py) and lib_manager.py have always written
('ok', 'syncing', 'sync_error'). 在通过纯 alembic 路径升级的 DB 上，第一次
`lib_manager.py import` 会抛 `invalid input value for enum sync_status_enum`。

复杂之处：`app/main.py:_init_db` 会在 backend 启动时跑 `Base.metadata.create_all`，
**先于**任何 alembic 升级生效——所以大多数实际运行的 dev DB 里 enum 已经被 ORM
创建成 ('ok','syncing','sync_error')。本 migration 必须幂等：

  - 若 DB 是 ('pending','synced','error') → 改名到 ORM 值。
  - 若 DB 已是 ORM 值 → no-op。
  - 若混合状态 → 按存在与否分别处理。

Revision ID: 003
Revises: 002
Create Date: 2026-05-14 00:00:00.000000
"""
from __future__ import annotations
from typing import Sequence, Union

from alembic import op


revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_UPGRADE_SQL = """
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_enum
        WHERE enumtypid = 'sync_status_enum'::regtype AND enumlabel = 'pending'
    ) THEN
        ALTER TYPE sync_status_enum RENAME VALUE 'pending' TO 'syncing';
    END IF;
    IF EXISTS (
        SELECT 1 FROM pg_enum
        WHERE enumtypid = 'sync_status_enum'::regtype AND enumlabel = 'synced'
    ) THEN
        ALTER TYPE sync_status_enum RENAME VALUE 'synced' TO 'ok';
    END IF;
    IF EXISTS (
        SELECT 1 FROM pg_enum
        WHERE enumtypid = 'sync_status_enum'::regtype AND enumlabel = 'error'
    ) THEN
        ALTER TYPE sync_status_enum RENAME VALUE 'error' TO 'sync_error';
    END IF;
END$$;
"""


_DOWNGRADE_SQL = """
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_enum
        WHERE enumtypid = 'sync_status_enum'::regtype AND enumlabel = 'sync_error'
    ) THEN
        ALTER TYPE sync_status_enum RENAME VALUE 'sync_error' TO 'error';
    END IF;
    IF EXISTS (
        SELECT 1 FROM pg_enum
        WHERE enumtypid = 'sync_status_enum'::regtype AND enumlabel = 'ok'
    ) THEN
        ALTER TYPE sync_status_enum RENAME VALUE 'ok' TO 'synced';
    END IF;
    IF EXISTS (
        SELECT 1 FROM pg_enum
        WHERE enumtypid = 'sync_status_enum'::regtype AND enumlabel = 'syncing'
    ) THEN
        ALTER TYPE sync_status_enum RENAME VALUE 'syncing' TO 'pending';
    END IF;
END$$;
"""


def upgrade() -> None:
    op.execute(_UPGRADE_SQL)
    # server_default 对齐 ORM (default='ok')。如果 templates 表不存在则跳过（极端
    # 场景：纯 alembic 路径但 templates 创建失败）。
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.columns
                       WHERE table_name='templates' AND column_name='sync_status') THEN
                ALTER TABLE templates ALTER COLUMN sync_status SET DEFAULT 'ok';
            END IF;
        END$$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM information_schema.columns
                       WHERE table_name='templates' AND column_name='sync_status') THEN
                ALTER TABLE templates ALTER COLUMN sync_status SET DEFAULT 'pending';
            END IF;
        END$$;
        """
    )
    op.execute(_DOWNGRADE_SQL)
