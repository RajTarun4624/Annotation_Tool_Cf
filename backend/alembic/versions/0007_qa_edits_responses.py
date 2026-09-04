"""QA edits an annotator's response in place - audit columns

QA reviewers correct a specific annotator's response instead of writing a
separate QA answer. The first edit snapshots the original into
``original_data``; ``qa_edited_by`` / ``qa_edited_by_name`` / ``qa_edited_at``
record who changed it last.

Revision ID: 0007_qa_edits
Revises: 0006_claim_leases
Create Date: 2026-09-04
"""
from typing import Sequence, Union

from alembic import op

from app.core.schema_patches import STATEMENTS_0007  # noqa: E402

revision: str = "0007_qa_edits"
down_revision: Union[str, None] = "0006_claim_leases"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for stmt in STATEMENTS_0007:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in [
        "ALTER TABLE task_annotations DROP COLUMN IF EXISTS qa_edited_at",
        "ALTER TABLE task_annotations DROP COLUMN IF EXISTS qa_edited_by_name",
        "ALTER TABLE task_annotations DROP COLUMN IF EXISTS qa_edited_by",
        "ALTER TABLE task_annotations DROP COLUMN IF EXISTS original_data",
    ]:
        op.execute(stmt)
