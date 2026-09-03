"""Data-integrity checks to run after a load test (or any time).

    .venv/Scripts/python.exe -m scripts.loadtest.check

Every query must return 0 rows. Exit code 1 when any invariant is violated.
"""

from __future__ import annotations

import sys

sys.path.insert(0, ".")

from sqlalchemy import text  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402

CHECKS = {
    "task has more submitted responses than its queue requires": """
        SELECT t.id, q.required_annotators, COUNT(a.id) AS submitted
        FROM tasks t JOIN queues q ON q.id = t.queue_id
        JOIN task_annotations a ON a.task_id = t.id AND a.status = 'submitted'
        GROUP BY t.id, q.required_annotators HAVING COUNT(a.id) > q.required_annotators
    """,
    "duplicate OPEN response for the same user on one task": """
        SELECT task_id, user_id, COUNT(*) FROM task_annotations
        WHERE status IN ('draft','returned') GROUP BY task_id, user_id HAVING COUNT(*) > 1
    """,
    "submitted_count out of sync with submitted rows": """
        SELECT t.id, t.submitted_count, COUNT(a.id) FILTER (WHERE a.status = 'submitted') AS actual
        FROM tasks t LEFT JOIN task_annotations a ON a.task_id = t.id
        GROUP BY t.id, t.submitted_count
        HAVING t.submitted_count <> COUNT(a.id) FILTER (WHERE a.status = 'submitted')
    """,
    "task status 'submitted' but fewer responses than required": """
        SELECT t.id FROM tasks t JOIN queues q ON q.id = t.queue_id
        WHERE t.status = 'submitted' AND t.submitted_count < q.required_annotators
    """,
    "task awaiting review (submitted) without a QA queue": """
        SELECT id FROM tasks WHERE status = 'submitted' AND qa_queue_id IS NULL
    """,
    "approved task without a final record or detached from QA": """
        SELECT id FROM tasks WHERE status = 'approved' AND (final_record IS NULL OR qa_queue_id IS NULL)
    """,
    "returned task still attached to QA or carrying a final record": """
        SELECT id FROM tasks WHERE status = 'returned' AND (qa_queue_id IS NOT NULL OR final_record IS NOT NULL)
    """,
    "approved task still holding a QA owner": """
        SELECT id FROM tasks WHERE status IN ('approved','returned') AND qa_owner_id IS NOT NULL
    """,
    "production queue with more than one QA queue": """
        SELECT source_production_queue_id, COUNT(*) FROM queues
        WHERE annotation_type = 'qa' AND source_production_queue_id IS NOT NULL
        GROUP BY source_production_queue_id HAVING COUNT(*) > 1
    """,
    "tasks_output row without its annotation": """
        SELECT o.id FROM tasks_output o LEFT JOIN task_annotations a ON a.id = o.annotation_id
        WHERE o.annotation_id IS NOT NULL AND a.id IS NULL
    """,
}


def main() -> int:
    db = SessionLocal()
    failed = 0
    try:
        for label, sql in CHECKS.items():
            rows = db.execute(text(sql)).fetchall()
            status = "OK " if not rows else "FAIL"
            print(f"[{status}] {label}: {len(rows)} row(s)")
            for r in rows[:5]:
                print("       ", tuple(r))
            if rows:
                failed += 1
        totals = db.execute(text(
            "SELECT (SELECT COUNT(*) FROM tasks) AS tasks, (SELECT COUNT(*) FROM task_annotations) AS responses, "
            "(SELECT COUNT(*) FROM tasks WHERE status='submitted') AS awaiting_qa, "
            "(SELECT COUNT(*) FROM tasks WHERE status='approved') AS approved, "
            "(SELECT COUNT(*) FROM task_annotations WHERE status='draft') AS open_drafts"
        )).mappings().one()
        print("totals:", dict(totals))
    finally:
        db.close()
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
