"""claim leases, QA ownership columns, open-response uniqueness, hot-path indexes

Concurrency safety for 200+ annotators:
- task_annotations.last_seen_at: heartbeat of the production claim (lease).
- tasks.qa_owner_id / qa_owner_seen_at: which reviewer holds a QA task + lease.
- uq_task_annotations_open: at most one open (draft/returned) response per
  user per task, so a replayed claim cannot create a phantom row.
- composite indexes on the columns every claim / summary query filters by.

Revision ID: 0006_claim_leases
Revises: 0005_multi_response
Create Date: 2026-09-03
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0006_claim_leases"
down_revision: Union[str, None] = "0005_multi_response"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Single source of truth shared with app.core.database.ensure_indexes so a
# create_all() database and a migrated database end up with the same schema.
from app.core.schema_patches import STATEMENTS_0006  # noqa: E402


def upgrade() -> None:
    for stmt in STATEMENTS_0006:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in [
        "DROP INDEX IF EXISTS ix_audit_logs_timestamp",
        "DROP INDEX IF EXISTS ix_tasks_qa_owner_id",
        "DROP INDEX IF EXISTS ix_tasks_qa_queue_status",
        "DROP INDEX IF EXISTS ix_tasks_queue_status",
        "DROP INDEX IF EXISTS ix_task_annotations_user_status",
        "DROP INDEX IF EXISTS ix_task_annotations_task_status",
        "DROP INDEX IF EXISTS uq_task_annotations_open",
        "ALTER TABLE tasks DROP COLUMN IF EXISTS qa_owner_seen_at",
        "ALTER TABLE tasks DROP COLUMN IF EXISTS qa_owner_id",
        "ALTER TABLE task_annotations DROP COLUMN IF EXISTS last_seen_at",
    ]:
        op.execute(stmt)
