"""Idempotent SQL patches shared by alembic migrations and ensure_indexes().

Every statement is safe to re-run (IF NOT EXISTS / IF EXISTS / WHERE-guarded),
so a database created by ``Base.metadata.create_all`` and one that went
through ``alembic upgrade head`` converge on the same schema. Keep this list
append-only; a new migration adds its statements here AND references them
from its ``upgrade()``.
"""

# alembic 0005: several responses per annotator per task.
STATEMENTS_0005 = [
    "ALTER TABLE task_annotations DROP CONSTRAINT IF EXISTS uq_task_annotations_task_user",
    "ALTER TABLE tasks_output DROP CONSTRAINT IF EXISTS uq_tasks_output_task_user",
    "ALTER TABLE tasks_output ADD COLUMN IF NOT EXISTS annotation_id UUID NULL",
    "CREATE INDEX IF NOT EXISTS ix_tasks_output_annotation_id ON tasks_output (annotation_id)",
]

# alembic 0006: claim leases, QA ownership, open-response uniqueness, indexes.
STATEMENTS_0006 = [
    "ALTER TABLE task_annotations ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMP NULL",
    "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS qa_owner_id UUID NULL REFERENCES users(id) ON DELETE SET NULL",
    "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS qa_owner_seen_at TIMESTAMP NULL",
    # Backfill: existing drafts were last touched at updated_at.
    "UPDATE task_annotations SET last_seen_at = COALESCE(updated_at, created_at) "
    "WHERE last_seen_at IS NULL AND status = 'draft'",
    # Backfill the QA owner from the legacy draft_data.user_id payload.
    "UPDATE tasks SET qa_owner_id = (draft_data->>'user_id')::uuid, "
    "qa_owner_seen_at = COALESCE(updated_at, created_at) "
    "WHERE qa_owner_id IS NULL AND status = 'submitted' "
    "AND draft_data ? 'user_id' AND (draft_data->>'user_id') ~ '^[0-9a-fA-F-]{36}$' "
    "AND EXISTS (SELECT 1 FROM users u WHERE u.id = (draft_data->>'user_id')::uuid)",
    # Dedupe open responses before the unique index: keep the most recent row.
    "DELETE FROM task_annotations a USING task_annotations b "
    "WHERE a.task_id = b.task_id AND a.user_id = b.user_id "
    "AND a.status IN ('draft','returned') AND b.status IN ('draft','returned') "
    "AND (COALESCE(a.updated_at, a.created_at), a.id) < (COALESCE(b.updated_at, b.created_at), b.id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_task_annotations_open ON task_annotations (task_id, user_id) "
    "WHERE status IN ('draft', 'returned')",
    "CREATE INDEX IF NOT EXISTS ix_task_annotations_task_status ON task_annotations (task_id, status)",
    "CREATE INDEX IF NOT EXISTS ix_task_annotations_user_status ON task_annotations (user_id, status)",
    "CREATE INDEX IF NOT EXISTS ix_tasks_queue_status ON tasks (queue_id, status)",
    "CREATE INDEX IF NOT EXISTS ix_tasks_qa_queue_status ON tasks (qa_queue_id, status)",
    "CREATE INDEX IF NOT EXISTS ix_tasks_qa_owner_id ON tasks (qa_owner_id)",
    "CREATE INDEX IF NOT EXISTS ix_audit_logs_timestamp ON audit_logs (timestamp)",
]

ALL_STATEMENTS = STATEMENTS_0005 + STATEMENTS_0006
