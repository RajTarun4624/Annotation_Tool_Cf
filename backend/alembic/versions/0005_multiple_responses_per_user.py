"""allow several responses per annotator per task

Consensus needs N responses per task, not N distinct people: the same
annotator may answer a task more than once (response 1, response 2, ...).
Drops the (task_id, user_id) uniqueness on task_annotations and tasks_output
and links every tasks_output row to its annotation.

Revision ID: 0005_multi_response
Revises: 0004_tasks_output
Create Date: 2026-09-03
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision: str = "0005_multi_response"
down_revision: Union[str, None] = "0004_tasks_output"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE task_annotations DROP CONSTRAINT IF EXISTS uq_task_annotations_task_user")
    op.execute("ALTER TABLE tasks_output DROP CONSTRAINT IF EXISTS uq_tasks_output_task_user")
    op.execute("ALTER TABLE tasks_output ADD COLUMN IF NOT EXISTS annotation_id UUID NULL")
    op.execute("CREATE INDEX IF NOT EXISTS ix_tasks_output_annotation_id ON tasks_output (annotation_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_tasks_output_annotation_id")
    op.execute("ALTER TABLE tasks_output DROP COLUMN IF EXISTS annotation_id")
    # Re-adding the unique constraints would fail once several responses exist; left out on purpose.
