"""create tasks_output table

Stores submitted annotator outputs in a dedicated PostgreSQL table.

Revision ID: 0004_tasks_output
Revises: 0003_queue_source
Create Date: 2026-09-02
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


# revision identifiers, used by Alembic.
revision: str = "0004_tasks_output"
down_revision: Union[str, None] = "0003_queue_source"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tasks_output",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("task_id", UUID(as_uuid=True), sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("user_name", sa.String(), nullable=True),
        sa.Column("queue_id", UUID(as_uuid=True), sa.ForeignKey("queues.id", ondelete="CASCADE"), nullable=True),
        sa.Column("dataset", sa.String(), nullable=True),
        sa.Column("input_text", sa.Text(), nullable=True),
        sa.Column("data_type", sa.String(), nullable=True),
        sa.Column("data_structure", sa.String(), nullable=True),
        sa.Column("attack_type", JSONB(), nullable=True, default=list),
        sa.Column("attack_subcategory", JSONB(), nullable=True, default=list),
        sa.Column("domain", sa.String(), nullable=True),
        sa.Column("role", sa.String(), nullable=True),
        sa.Column("verified", sa.Boolean(), nullable=True, default=False),
        sa.Column("language", sa.String(), nullable=True, default="en"),
        sa.Column("document_edited", sa.Boolean(), nullable=True, default=False),
        sa.Column("source_description", sa.Text(), nullable=True),
        sa.Column("severity_j", sa.Integer(), nullable=True, default=0),
        sa.Column("severity_i", sa.Integer(), nullable=True, default=0),
        sa.Column("severity_l", sa.Integer(), nullable=True, default=0),
        sa.Column("intention", sa.String(), nullable=True),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column("jailbreak", sa.Boolean(), nullable=True, default=False),
        sa.Column("prompt_injection", sa.Boolean(), nullable=True, default=False),
        sa.Column("prompt_leakage", sa.Boolean(), nullable=True, default=False),
        sa.Column("annotation_data", JSONB(), nullable=True, default=dict),
        sa.Column("elapsed_seconds", sa.Integer(), nullable=True, default=0),
        sa.Column("status", sa.String(), nullable=True, default="submitted"),
        sa.Column("submitted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("task_id", "user_id", name="uq_tasks_output_task_user"),
    )
    op.create_index("ix_tasks_output_task_id", "tasks_output", ["task_id"])
    op.create_index("ix_tasks_output_user_id", "tasks_output", ["user_id"])
    op.create_index("ix_tasks_output_queue_id", "tasks_output", ["queue_id"])
    op.create_index("ix_tasks_output_dataset", "tasks_output", ["dataset"])


def downgrade() -> None:
    op.drop_index("ix_tasks_output_dataset", table_name="tasks_output")
    op.drop_index("ix_tasks_output_queue_id", table_name="tasks_output")
    op.drop_index("ix_tasks_output_user_id", table_name="tasks_output")
    op.drop_index("ix_tasks_output_task_id", table_name="tasks_output")
    op.drop_table("tasks_output")
