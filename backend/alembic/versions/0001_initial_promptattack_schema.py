"""initial promptattack schema

Fresh schema for the Prompt Attack Annotation Platform. Mirrors app/models
exactly (column names, nullability, FKs with ondelete, indexes). Server-side
defaults are declared where the previous (table-annotation) migrations had
them so rows inserted outside the ORM get the same values the models apply.

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-02

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---- features -----------------------------------------------------------
    op.create_table(
        "features",
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("icon", sa.String(), nullable=True),
        sa.Column("order", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("key"),
    )

    # ---- roles --------------------------------------------------------------
    op.create_table(
        "roles",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column("permissions", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    # ---- users --------------------------------------------------------------
    op.create_table(
        "users",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("full_name", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("hashed_password", sa.String(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column("role_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # ---- user_sessions ------------------------------------------------------
    op.create_table(
        "user_sessions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("refresh_token_hash", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("is_revoked", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("replaced_by_session_id", sa.UUID(), nullable=True),
        sa.Column("user_agent", sa.String(), nullable=True),
        sa.Column("ip_address", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["replaced_by_session_id"], ["user_sessions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_sessions_refresh_token_hash", "user_sessions", ["refresh_token_hash"])
    op.create_index("ix_user_sessions_expires_at", "user_sessions", ["expires_at"])
    op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"])

    # ---- audit_logs ---------------------------------------------------------
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("resource_type", sa.String(), nullable=True),
        sa.Column("resource_id", sa.String(), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("timestamp", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # ---- projects -----------------------------------------------------------
    op.create_table(
        "projects",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("media_type", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # ---- project_assigned_users --------------------------------------------
    op.create_table(
        "project_assigned_users",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("project_id", "user_id"),
    )

    # ---- queues -------------------------------------------------------------
    op.create_table(
        "queues",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column("task_name", sa.String(), nullable=True),
        sa.Column("batch_name", sa.String(), nullable=True),
        sa.Column("annotation_type", sa.String(), nullable=True),
        sa.Column("priority", sa.String(), nullable=True),
        sa.Column("sla_hours", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("assigned_user_id", sa.UUID(), nullable=True),
        sa.Column("linked_qa_queue_id", sa.UUID(), nullable=True),
        sa.Column("source_production_queue_id", sa.UUID(), nullable=True),
        sa.Column("timer_seconds", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["assigned_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["linked_qa_queue_id"], ["queues.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_production_queue_id"], ["queues.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # ---- queue_assigned_users ----------------------------------------------
    op.create_table(
        "queue_assigned_users",
        sa.Column("queue_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["queue_id"], ["queues.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("queue_id", "user_id"),
    )
    op.create_index("ix_queue_assigned_users_user_id", "queue_assigned_users", ["user_id"])

    # ---- tasks --------------------------------------------------------------
    op.create_table(
        "tasks",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("queue_id", sa.UUID(), nullable=False),
        sa.Column("file_url", sa.String(), nullable=True),
        sa.Column("file_name", sa.String(), nullable=True),
        sa.Column("file_type", sa.String(), nullable=True),
        sa.Column("batch_name", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=True, server_default="pending"),
        sa.Column("environment", sa.String(), nullable=True, server_default="production"),
        sa.Column("assigned_to", sa.UUID(), nullable=True),
        sa.Column("assigned_to_name", sa.String(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("paused_at", sa.DateTime(), nullable=True),
        sa.Column("annotation_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True, server_default="{}"),
        sa.Column("draft_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True, server_default="{}"),
        sa.Column("annotation_version", sa.Integer(), nullable=True, server_default="1"),
        sa.Column("annotation_history", postgresql.JSONB(astext_type=sa.Text()), nullable=True, server_default="[]"),
        sa.Column("timer_seconds", sa.Integer(), nullable=True, server_default="7200"),
        sa.Column("elapsed_seconds", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("declined_reason", sa.String(), nullable=True, server_default=""),
        sa.Column("qa_notes", sa.String(), nullable=True, server_default=""),
        sa.Column("submitted_by", sa.String(), nullable=True, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["queue_id"], ["queues.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assigned_to"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tasks_status", "tasks", ["status"])
    op.create_index("ix_tasks_created_at", "tasks", ["created_at"])
    op.create_index("ix_tasks_submitted_at", "tasks", ["submitted_at"])
    op.create_index("ix_tasks_started_at", "tasks", ["started_at"])
    op.create_index("ix_tasks_queue_id", "tasks", ["queue_id"])
    op.create_index("ix_tasks_batch_name", "tasks", ["batch_name"])
    op.create_index("ix_tasks_environment", "tasks", ["environment"])


def downgrade() -> None:
    # Reverse FK order.
    op.drop_index("ix_tasks_environment", table_name="tasks")
    op.drop_index("ix_tasks_batch_name", table_name="tasks")
    op.drop_index("ix_tasks_queue_id", table_name="tasks")
    op.drop_index("ix_tasks_started_at", table_name="tasks")
    op.drop_index("ix_tasks_submitted_at", table_name="tasks")
    op.drop_index("ix_tasks_created_at", table_name="tasks")
    op.drop_index("ix_tasks_status", table_name="tasks")
    op.drop_table("tasks")

    op.drop_index("ix_queue_assigned_users_user_id", table_name="queue_assigned_users")
    op.drop_table("queue_assigned_users")

    op.drop_table("queues")
    op.drop_table("project_assigned_users")
    op.drop_table("projects")
    op.drop_table("audit_logs")

    op.drop_index("ix_user_sessions_user_id", table_name="user_sessions")
    op.drop_index("ix_user_sessions_expires_at", table_name="user_sessions")
    op.drop_index("ix_user_sessions_refresh_token_hash", table_name="user_sessions")
    op.drop_table("user_sessions")

    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
    op.drop_table("roles")
    op.drop_table("features")
