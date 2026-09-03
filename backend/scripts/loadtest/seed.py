"""Seed the load-test dataset directly in the database.

    .venv/Scripts/python.exe -m scripts.loadtest.seed --annotators 200 --reviewers 30 --queues 20 --tasks 500

Creates N annotator accounts (role User), M reviewer accounts (role QA), and
Q production queues of T tasks each (plus their linked QA queues). Every
annotator is assigned to every production queue and every reviewer to every
QA queue - the widest "my queues" list, i.e. the worst case for the per-user
queue listing. Idempotent per tag: re-running with the same --tag reuses users
and adds queues.
"""

from __future__ import annotations

import argparse
import sys
import time
import uuid
from datetime import UTC, datetime

sys.path.insert(0, ".")

from sqlalchemy import insert  # noqa: E402

from app.core.database import SessionLocal, ensure_indexes, startup_lock  # noqa: E402
from app.core.security import get_password_hash  # noqa: E402
from app.models import Queue, Role, Task, User  # noqa: E402
from app.models.queue import queue_assigned_users  # noqa: E402
from scripts.loadtest.common import PASSWORD, PROMPT, TAG_PREFIX, ann_email, qa_email  # noqa: E402


def _ensure_users(db, emails: list[str], role_name: str, name_prefix: str) -> list[User]:
    role = db.query(Role).filter(Role.name == role_name).first()
    if role is None:
        raise SystemExit(f"role {role_name!r} missing - start the app once so the seed creates it")
    existing = {u.email: u for u in db.query(User).filter(User.email.in_(emails)).all()}
    hashed = get_password_hash(PASSWORD)  # one hash for all (same password)
    now = datetime.now(UTC)
    created = 0
    for i, email in enumerate(emails, 1):
        if email in existing:
            continue
        u = User(id=uuid.uuid4(), full_name=f"{name_prefix} {i:03d}", email=email, hashed_password=hashed,
                 role_id=role.id, is_active=True, created_at=now, updated_at=now)
        db.add(u)
        existing[email] = u
        created += 1
    db.commit()
    print(f"  {role_name}: {len(emails)} accounts ({created} created)")
    return [existing[e] for e in emails]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--annotators", type=int, default=200)
    ap.add_argument("--reviewers", type=int, default=30)
    ap.add_argument("--queues", type=int, default=20)
    ap.add_argument("--tasks", type=int, default=500)
    ap.add_argument("--required", type=int, default=3)
    ap.add_argument("--tag", default=time.strftime("%m%d%H%M"))
    args = ap.parse_args()

    with startup_lock():
        ensure_indexes()

    db = SessionLocal()
    try:
        t0 = time.perf_counter()
        print("users:")
        annotators = _ensure_users(db, [ann_email(i) for i in range(1, args.annotators + 1)], "User", "LT Annotator")
        reviewers = _ensure_users(db, [qa_email(i) for i in range(1, args.reviewers + 1)], "QA", "LT Reviewer")

        now = datetime.now(UTC)
        prod_ids: list[uuid.UUID] = []
        qa_ids: list[uuid.UUID] = []
        for k in range(1, args.queues + 1):
            name = f"{TAG_PREFIX}{args.tag}-{k:02d}"
            prod = Queue(id=uuid.uuid4(), name=name, annotation_type="production", status="active",
                         required_annotators=args.required, timer_seconds=7200, batch_name=f"LT-{args.tag}",
                         task_name="Load test", created_at=now, updated_at=now)
            qa = Queue(id=uuid.uuid4(), name=f"{name} - QA", annotation_type="qa", status="active",
                       required_annotators=1, timer_seconds=7200, batch_name=f"LT-{args.tag}",
                       task_name="Load test", source_production_queue_id=prod.id, created_at=now, updated_at=now)
            prod.linked_qa_queue_id = qa.id
            prod.assigned_user_id = annotators[0].id
            qa.assigned_user_id = reviewers[0].id if reviewers else None
            db.add(prod)
            db.add(qa)
            db.flush()
            rows = [
                dict(
                    id=uuid.uuid4(), queue_id=prod.id, dataset=f"lt_{args.tag}_{k:02d}_{i:05d}",
                    input_text=PROMPT.format(n=i, q=k), sequence=i, status="pending", source="real_user",
                    meta_data={"domain": "other"}, draft_data={}, annotation_data={}, annotation_history=[],
                    submitted_count=0, timer_seconds=7200, elapsed_seconds=0, annotation_version=1,
                    batch_name=f"LT-{args.tag}", environment="production", created_at=now, updated_at=now,
                )
                for i in range(1, args.tasks + 1)
            ]
            for s in range(0, len(rows), 1000):
                db.execute(insert(Task), rows[s:s + 1000])
            db.execute(insert(queue_assigned_users), [{"queue_id": prod.id, "user_id": u.id} for u in annotators])
            if reviewers:
                db.execute(insert(queue_assigned_users), [{"queue_id": qa.id, "user_id": u.id} for u in reviewers])
            db.commit()
            prod_ids.append(prod.id)
            qa_ids.append(qa.id)
            print(f"  queue {name}: {args.tasks} tasks")
        print(f"seeded {args.queues} x {args.tasks} = {args.queues * args.tasks} tasks in {time.perf_counter() - t0:.1f}s")
        print(f"tag={args.tag}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
