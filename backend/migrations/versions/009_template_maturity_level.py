"""Add templates.maturity_level column (FEAT-13 模板成熟度门控).

新增 PostgreSQL ENUM `template_maturity_enum`('production','experimental','draft')
和 `templates.maturity_level` 列（NOT NULL，server_default 'experimental'），用于
RAG 召回主库的生产门控。Backfill 规则：

  id ~ '^(sva|cov)_.+_v[0-9]+$'  → 'production'
  其余（含 is_active=false / L6_E2E_* / 临时模板）→ 'experimental'

注意：旧 `maturity` 列（maturity_enum: draft/validated/production，"开发成熟度"语义）
不动，新列 `maturity_level`（template_maturity_enum: production/experimental/draft，
"生产门控"语义）与之并存，绝不能混用。

⚠️ 部署顺序警告：migration 009 跑完后，Qdrant collection 中现有 points
**没有** maturity_level payload 字段，stage1 Filter 会过滤掉所有 → RAG 全空
→ EmptyRetrievalError 503。必须在新代码启动前/启动后立即执行：

    python lib_manager.py rebuild --all

注意必须用 --all：默认 rebuild 只刷 sync_status='syncing' 的行，而 migration 009
不改 sync_status，存量行仍 'ok'，默认命令"待同步 0 条"直接返回。--all 跳过该过滤，
全量重写所有 active 模板的 Qdrant payload，让 maturity_level 字段进入存量 points。

Revision ID: 009
Revises: 008
Create Date: 2026-06-03 00:00:00.000000
"""
from __future__ import annotations
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 幂等保护：若残留旧 ENUM type 重跑会失败。
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'template_maturity_enum') THEN
                CREATE TYPE template_maturity_enum AS ENUM ('production', 'experimental', 'draft');
            END IF;
        END$$;
        """
    )

    op.add_column(
        "templates",
        sa.Column(
            "maturity_level",
            sa.Enum(
                "production",
                "experimental",
                "draft",
                name="template_maturity_enum",
                create_type=False,
            ),
            nullable=False,
            server_default="experimental",
        ),
    )

    # Backfill：仅官方命名规范（sva_*_v* / cov_*_v*）模板升为 production；其余包括
    # L6_E2E_* / 临时贡献模板 / is_active=false 行 全部 experimental。
    op.execute(
        """
        UPDATE templates
           SET maturity_level = 'production'
         WHERE id ~ '^(sva|cov)_.+_v[0-9]+$'
        """
    )

    print(
        "\n[WARN][migration 009] templates.maturity_level 列已加，但 Qdrant collection "
        "中现有 points 仍**无** maturity_level payload 字段。"
        "stage1 Filter 将过滤掉所有 → EmptyRetrievalError 503。"
        "必须在新代码部署前/后立即执行：python lib_manager.py rebuild --all "
        "（默认 rebuild 只刷 sync_status=syncing 的行；--all 跳过该过滤，"
        "全量重写 Qdrant payload，让 maturity_level 字段进入存量 points）。\n"
    )


def downgrade() -> None:
    op.drop_column("templates", "maturity_level")
    # 故意不带 IF EXISTS：如果 type 仍被其他表/列引用，DROP 会失败可见，
    # 比静默残留好——回滚出现 type 残留意味着 schema 状态不一致，必须人工介入。
    op.execute("DROP TYPE template_maturity_enum")
