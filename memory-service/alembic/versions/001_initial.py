"""Initial migration: all tables + RLS + pgvector extension

Revision ID: 001_initial
Revises:
Create Date: 2026-06-01 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector


revision: str = "001_initial"
down_revision: str | None = None
branch_labels: tuple[str, ...] | None = None
depends_on: str | None = None


def upgrade() -> None:
    # Enable pgvector extension
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Tenant memory table
    op.create_table(
        "tenant_memory",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("fact", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), server_default=sa.text("1.0")),
        sa.Column("embedding", Vector(1024), nullable=True),
        sa.Column("needs_embedding", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_tenant_mem_tenant", "tenant_memory", ["tenant_id"])
    op.create_index(
        "idx_tenant_mem_embedding",
        "tenant_memory",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )

    # User memory table
    op.create_table(
        "user_memory",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("fact", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), server_default=sa.text("1.0")),
        sa.Column("embedding", Vector(1024), nullable=True),
        sa.Column("needs_embedding", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_user_mem_tenant_user", "user_memory", ["tenant_id", "user_id"])
    op.create_index(
        "idx_user_mem_embedding",
        "user_memory",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )

    # Tasks table
    op.create_table(
        "tasks",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("control_id", sa.Text(), nullable=True),
        sa.Column("framework_id", sa.Text(), nullable=True),
        sa.Column("assignee_id", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'open'")),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("blocked_reason", sa.Text(), nullable=True),
        sa.Column("metadata_", sa.JSON(), nullable=True),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_tasks_tenant", "tasks", ["tenant_id"])
    op.create_index("idx_tasks_assignee", "tasks", ["tenant_id", "assignee_id", "status"])
    op.create_index("idx_tasks_control", "tasks", ["tenant_id", "control_id"])

    # Eval history table
    op.create_table(
        "eval_history",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("framework", sa.Text(), nullable=False),
        sa.Column("control_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("evidence_hash", sa.Text(), nullable=True),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("model_used", sa.Text(), nullable=True),
        sa.Column("tier_used", sa.Text(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_eval_tenant_fw_ctrl", "eval_history", ["tenant_id", "framework", "control_id"])

    # Patterns table (cross-tenant)
    op.create_table(
        "patterns",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("pattern", sa.Text(), nullable=False),
        sa.Column("context", sa.JSON(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("hit_count", sa.Integer(), server_default=sa.text("1")),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(1024), nullable=True),
        sa.Column("needs_embedding", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decay_applied_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "idx_patterns_embedding",
        "patterns",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )

    # Skills table
    op.create_table(
        "skills",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("current_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Skill versions table
    op.create_table(
        "skill_versions",
        sa.Column("skill_id", sa.Text(), sa.ForeignKey("skills.id"), primary_key=True),
        sa.Column("version", sa.Integer(), primary_key=True),
        sa.Column("prompt_template", sa.Text(), nullable=False),
        sa.Column("config", sa.JSON(), nullable=True),
        sa.Column("author", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'active'")),
        sa.Column("metrics", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Interactions table
    op.create_table(
        "interactions",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("session_id", sa.Text(), nullable=False),
        sa.Column("messages", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_interactions_tenant_user", "interactions", ["tenant_id", "user_id"])
    op.create_index("idx_interactions_tenant_created", "interactions", ["tenant_id", "created_at"])

    # Audit trail table (append-only)
    op.create_table(
        "audit_trail",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("operation", sa.Text(), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=True),
        sa.Column("agent", sa.Text(), nullable=True),
        sa.Column("trace_id", sa.Text(), nullable=True),
        sa.Column("data", sa.JSON(), nullable=True),
    )
    op.create_index("idx_audit_tenant_ts", "audit_trail", ["tenant_id", "timestamp"])

    # Agent registry table
    op.create_table(
        "agent_registry",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("capabilities", sa.JSON(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'active'")),
        sa.Column("metadata_", sa.JSON(), nullable=True),
        sa.Column("registered_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_heartbeat", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Jobs table (for StateClient)
    op.create_table(
        "jobs",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # RLS policies for tenant-scoped tables
    for table in ["tenant_memory", "user_memory", "tasks", "eval_history", "interactions", "audit_trail"]:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation_{table} ON {table} "
            f"USING (tenant_id = current_setting('app.current_tenant_id', true))"
        )


def downgrade() -> None:
    for table in ["audit_trail", "interactions", "eval_history", "tasks", "user_memory", "tenant_memory"]:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    op.drop_table("jobs")
    op.drop_table("agent_registry")
    op.drop_table("audit_trail")
    op.drop_table("interactions")
    op.drop_table("skill_versions")
    op.drop_table("skills")
    op.drop_table("patterns")
    op.drop_table("eval_history")
    op.drop_table("tasks")
    op.drop_table("user_memory")
    op.drop_table("tenant_memory")
    op.execute("DROP EXTENSION IF EXISTS vector")
