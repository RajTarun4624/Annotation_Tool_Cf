"""consensus annotations

Prompt-attack annotation with N-annotator consensus (SPEC2 section 3):

* queues.required_annotators
* tasks: dataset / input_text / sequence / source / meta_data /
  submitted_count / final_data / final_record / finalized_by(_name/_at) /
  qa_queue_id (+ indexes and FKs)
* new table task_annotations (one row per annotator per task)

Revision ID: 0002_consensus
Revises: 0001_initial
Create Date: 2026-09-02

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0002_consensus"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---- queues -------------------------------------------------------------
    op.add_column(
        "queues",
        sa.Column("required_annotators", sa.Integer(), nullable=False, server_default="3"),
    )

    # ---- tasks --------------------------------------------------------------
    op.add_column("tasks", sa.Column("dataset", sa.String(), nullable=True))
    op.add_column("tasks", sa.Column("input_text", sa.Text(), nullable=True))
    op.add_column("tasks", sa.Column("sequence", sa.Integer(), nullable=True, server_default="0"))
    op.add_column("tasks", sa.Column("source", sa.String(), nullable=True, server_default="real_user"))
    op.add_column(
        "tasks",
        sa.Column("meta_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True, server_default="{}"),
    )
    op.add_column("tasks", sa.Column("submitted_count", sa.Integer(), nullable=True, server_default="0"))
    op.add_column("tasks", sa.Column("final_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("tasks", sa.Column("final_record", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("tasks", sa.Column("finalized_by", sa.UUID(), nullable=True))
    op.add_column("tasks", sa.Column("finalized_by_name", sa.String(), nullable=True))
    op.add_column("tasks", sa.Column("finalized_at", sa.DateTime(), nullable=True))
    op.add_column("tasks", sa.Column("qa_queue_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_tasks_finalized_by_users",
        "tasks",
        "users",
        ["finalized_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_tasks_qa_queue_id_queues",
        "tasks",
        "queues",
        ["qa_queue_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_tasks_dataset", "tasks", ["dataset"])
    op.create_index("ix_tasks_qa_queue_id", "tasks", ["qa_queue_id"])

    # ---- task_annotations ---------------------------------------------------
    op.create_table(
        "task_annotations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("task_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("user_name", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=True, server_default="draft"),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=True, server_default="{}"),
        sa.Column("elapsed_seconds", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("submitted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", "user_id", name="uq_task_annotations_task_user"),
    )
    op.create_index("ix_task_annotations_task_id", "task_annotations", ["task_id"])
    op.create_index("ix_task_annotations_user_id", "task_annotations", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_task_annotations_user_id", table_name="task_annotations")
    op.drop_index("ix_task_annotations_task_id", table_name="task_annotations")
    op.drop_table("task_annotations")

    op.drop_index("ix_tasks_qa_queue_id", table_name="tasks")
    op.drop_index("ix_tasks_dataset", table_name="tasks")
    op.drop_constraint("fk_tasks_qa_queue_id_queues", "tasks", type_="foreignkey")
    op.drop_constraint("fk_tasks_finalized_by_users", "tasks", type_="foreignkey")
    op.drop_column("tasks", "qa_queue_id")
    op.drop_column("tasks", "finalized_at")
    op.drop_column("tasks", "finalized_by_name")
    op.drop_column("tasks", "finalized_by")
    op.drop_column("tasks", "final_record")
    op.drop_column("tasks", "final_data")
    op.drop_column("tasks", "submitted_count")
    op.drop_column("tasks", "meta_data")
    op.drop_column("tasks", "source")
    op.drop_column("tasks", "sequence")
    op.drop_column("tasks", "input_text")
    op.drop_column("tasks", "dataset")

    op.drop_column("queues", "required_annotators")
