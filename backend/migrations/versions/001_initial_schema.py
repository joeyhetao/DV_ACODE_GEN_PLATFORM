"""Initial schema: all tables

Revision ID: 001
Revises:
Create Date: 2024-01-01 00:00:00.000000

"""
from __future__ import annotations
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # users
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("username", sa.String(64), nullable=False, unique=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("hashed_password", sa.String(128), nullable=False),
        sa.Column(
            "role",
            sa.Enum("user", "lib_admin", "super_admin", name="user_role_enum"),
            nullable=False,
            server_default="user",
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # templates
    op.create_table(
        "templates",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("version", sa.String(20), nullable=False, server_default="1.0.0"),
        sa.Column("name", sa.String(256), nullable=False, unique=True),
        sa.Column(
            "code_type",
            sa.Enum("assertion", "coverage", name="code_type_enum"),
            nullable=False,
        ),
        sa.Column("subcategory", sa.String(64), nullable=True),
        sa.Column("protocol", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("tags", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("keywords", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("parameters", postgresql.JSONB(), nullable=True),
        sa.Column("template_body", sa.Text(), nullable=False),
        sa.Column(
            "maturity",
            sa.Enum("draft", "stable", "deprecated", name="maturity_enum"),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("related_ids", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("qdrant_point_id", sa.String(36), nullable=True),
        sa.Column(
            "sync_status",
            sa.Enum("pending", "synced", "error", name="sync_status_enum"),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.String(36), nullable=True),
    )
    op.create_index("ix_templates_code_type", "templates", ["code_type"])
    op.create_index("ix_templates_sync_status", "templates", ["sync_status"])

    # template_versions
    op.create_table(
        "template_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("template_id", sa.String(32), sa.ForeignKey("templates.id"), nullable=False),
        sa.Column("version", sa.String(20), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("change_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # generation_records
    op.create_table(
        "generation_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("original_intent", sa.Text(), nullable=False),
        sa.Column("normalized_intent", sa.Text(), nullable=True),
        sa.Column("intent_hash", sa.String(64), nullable=True, index=True),
        sa.Column("rag_top3", postgresql.JSONB(), nullable=True),
        sa.Column("template_id", sa.String(32), nullable=True),
        sa.Column("params_used", postgresql.JSONB(), nullable=True),
        sa.Column("output_code", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("cache_hit", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("intent_cache_hit", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # batch_jobs
    op.create_table(
        "batch_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("code_type", sa.String(32), nullable=False),
        sa.Column(
            "status",
            sa.Enum("pending", "running", "done", "failed", name="batch_status_enum"),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("total_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completed_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("result_url", sa.String(512), nullable=True),
        sa.Column("error_message", sa.String(512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )

    # llm_configs
    op.create_table(
        "llm_configs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column(
            "provider",
            sa.Enum("anthropic", "openai_compatible", name="llm_provider_enum"),
            nullable=False,
        ),
        sa.Column("base_url", sa.String(512), nullable=True),
        sa.Column("api_key_encrypted", sa.Text(), nullable=False),
        sa.Column("model_id", sa.String(128), nullable=False),
        sa.Column(
            "output_mode",
            sa.Enum("tool_calling", "json_mode", "prompt_json", name="llm_output_mode_enum"),
            nullable=False,
            server_default="tool_calling",
        ),
        sa.Column("temperature", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("max_tokens", sa.Integer(), nullable=False, server_default="512"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # contributions
    op.create_table(
        "template_contributions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("contributor_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("code_type", sa.String(32), nullable=False),
        sa.Column("original_intent", sa.Text(), nullable=False),
        sa.Column("original_row_json", postgresql.JSONB(), nullable=True),
        sa.Column("template_name", sa.String(256), nullable=False),
        sa.Column("subcategory", sa.String(64), nullable=True),
        sa.Column("protocol", sa.String(64), nullable=True),
        sa.Column("demo_code", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("keywords", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("parameter_defs", postgresql.JSONB(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("pending", "approved", "rejected", "needs_revision", "withdrawn",
                    name="contribution_status_enum"),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("reviewer_id", sa.String(36), nullable=True),
        sa.Column("reviewer_comment", sa.Text(), nullable=True),
        sa.Column("promoted_template_id", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # notifications
    op.create_table(
        "notifications",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("type", sa.String(64), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # audit_logs
    op.create_table(
        "admin_audit_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("operator_id", sa.String(36), nullable=False, index=True),
        sa.Column("action", sa.String(64), nullable=False, index=True),
        sa.Column("target_type", sa.String(64), nullable=False),
        sa.Column("target_id", sa.String(64), nullable=True),
        sa.Column("detail", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now(), index=True),
    )


def downgrade() -> None:
    op.drop_table("admin_audit_logs")
    op.drop_table("notifications")
    op.drop_table("template_contributions")
    op.drop_table("llm_configs")
    op.drop_table("batch_jobs")
    op.drop_table("generation_records")
    op.drop_table("template_versions")
    op.drop_table("templates")
    op.drop_table("users")
    op.execute("DROP TYPE IF EXISTS user_role_enum")
    op.execute("DROP TYPE IF EXISTS code_type_enum")
    op.execute("DROP TYPE IF EXISTS maturity_enum")
    op.execute("DROP TYPE IF EXISTS sync_status_enum")
    op.execute("DROP TYPE IF EXISTS batch_status_enum")
    op.execute("DROP TYPE IF EXISTS llm_provider_enum")
    op.execute("DROP TYPE IF EXISTS llm_output_mode_enum")
    op.execute("DROP TYPE IF EXISTS contribution_status_enum")
