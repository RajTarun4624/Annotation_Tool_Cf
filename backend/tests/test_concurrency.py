"""Concurrency invariants of the task lifecycle (real PostgreSQL, real threads).

Each thread opens its own ``SessionLocal`` and calls the crud layer directly,
so the row locks / unique index / lease rules are exercised exactly as the API
would under simultaneous requests. A ``threading.Barrier`` releases every
thread at the same instant.

Invariants proven here:
- claims: never more live claims on a task than ``required_annotators``;
- submits: never more than ``required`` stored responses, exactly one QA queue;
- one open draft per user per task even under a duplicated request;
- QA: a task is held by at most one reviewer; finalize vs return -> one winner;
- an expired lease frees the slot and an empty expired claim is purged.

Run from ``backend/``::

    .venv/Scripts/python.exe -m pytest tests/test_concurrency.py -q
"""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest

from app.core.config import settings
from app.core.database import SessionLocal, ensure_indexes, startup_lock
from app.core.errors import ConflictError
from app.core.security import get_password_hash
from app.crud import annotation as crud
from app.models import Queue, Task, TaskAnnotation, User

from tests.test_workspace_flow import ANNOTATION


# ─── Fixtures / helpers ─────────────────────────────────────────────────────

@pytest.fixture(scope="module", autouse=True)
def _schema():
    with startup_lock():
        ensure_indexes()


def _mk_users(db, n: int, suffix: str) -> list[dict]:
    users = []
    for k in range(n):
        u = User(
            id=uuid.uuid4(),
            full_name=f"Conc {k} {suffix}",
            email=f"conc{k}.{suffix}@flowtest.dev",
            hashed_password=get_password_hash("Conc@12345"),
            is_active=True,
        )
        db.add(u)
        users.append({"id": str(u.id), "full_name": u.full_name})
    db.commit()
    return users


def _mk_queue(db, suffix: str, n_tasks: int, required: int, annotation_type: str = "production") -> Queue:
    q = Queue(
        id=uuid.uuid4(),
        name=f"conc-{suffix}",
        annotation_type=annotation_type,
        status="active",
        required_annotators=required,
        timer_seconds=7200,
    )
    db.add(q)
    db.flush()
    for i in range(1, n_tasks + 1):
        db.add(Task(
            id=uuid.uuid4(),
            queue_id=q.id,
            dataset=f"conc_{suffix}_{i:04d}",
            input_text=f"Prompt {i} for concurrency test {suffix}. " * 5,
            sequence=i,
            status="pending",
            source="real_user",
            meta_data={},
        ))
    db.commit()
    db.refresh(q)
    return q


def _cleanup(queue_ids: list[uuid.UUID], user_ids: list[str]) -> None:
    db = SessionLocal()
    try:
        for qid in queue_ids:
            db.query(Queue).filter(Queue.source_production_queue_id == qid).delete(synchronize_session=False)
            db.query(Queue).filter(Queue.id == qid).delete(synchronize_session=False)
        if user_ids:
            db.query(User).filter(User.id.in_([uuid.UUID(u) for u in user_ids])).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def _run_parallel(fns):
    """Run callables simultaneously (barrier start); return their results / exceptions."""
    barrier = threading.Barrier(len(fns))
    results: list = [None] * len(fns)

    def wrap(i, fn):
        def _inner():
            db = SessionLocal()
            try:
                barrier.wait(timeout=30)
                results[i] = fn(db)
            except Exception as exc:  # noqa: BLE001 - captured for assertions
                results[i] = exc
            finally:
                db.close()
        return _inner

    with ThreadPoolExecutor(max_workers=len(fns)) as pool:
        futures = [pool.submit(wrap(i, fn)) for i, fn in enumerate(fns)]
        for f in futures:
            f.result(timeout=120)
    return results


def _task_open_counts(db, queue_id: uuid.UUID) -> dict[uuid.UUID, int]:
    rows = (
        db.query(TaskAnnotation.task_id)
        .join(Task, Task.id == TaskAnnotation.task_id)
        .filter(Task.queue_id == queue_id, TaskAnnotation.status.in_(("draft", "returned")))
        .all()
    )
    out: dict[uuid.UUID, int] = {}
    for (tid,) in rows:
        out[tid] = out.get(tid, 0) + 1
    return out


# ─── Tests ─────────────────────────────────────────────────────────────────

def test_parallel_claims_never_exceed_required():
    suffix = uuid.uuid4().hex[:8]
    db = SessionLocal()
    users = _mk_users(db, 8, suffix)
    q = _mk_queue(db, suffix, n_tasks=3, required=2)
    qid = q.id
    db.close()
    try:
        results = _run_parallel([(lambda u: (lambda s: crud.claim_next_task(s, qid, u, None)))(u) for u in users])
        errors = [r for r in results if isinstance(r, Exception)]
        assert not errors, errors
        claimed = [r for r in results if r]
        # 3 tasks x 2 slots = 6 claims for 8 annotators; two of them get nothing.
        assert len(claimed) == 6, results
        db = SessionLocal()
        counts = _task_open_counts(db, qid)
        db.close()
        assert all(n <= 2 for n in counts.values()), counts
        assert sum(counts.values()) == 6
    finally:
        _cleanup([qid], [u["id"] for u in users])


def test_parallel_submits_respect_cap_and_create_one_qa_queue():
    suffix = uuid.uuid4().hex[:8]
    db = SessionLocal()
    users = _mk_users(db, 6, suffix)
    q = _mk_queue(db, suffix, n_tasks=1, required=2)
    qid = q.id
    task_id = db.query(Task.id).filter(Task.queue_id == qid).scalar()
    db.close()
    try:
        def submit_as(u):
            def _do(s):
                task = crud.get_task(s, str(task_id))
                return crud.submit_annotation(s, task, u, dict(ANNOTATION), 30)
            return _do

        results = _run_parallel([submit_as(u) for u in users])
        ok = [r for r in results if r == []]
        conflicts = [r for r in results if isinstance(r, ConflictError)]
        other = [r for r in results if isinstance(r, Exception) and not isinstance(r, ConflictError)]
        assert not other, other
        assert len(ok) == 2, results
        assert len(conflicts) == 4, results

        db = SessionLocal()
        try:
            task = crud.get_task(db, str(task_id))
            submitted = [a for a in task.annotations if a.status == "submitted"]
            assert len(submitted) == 2
            assert task.submitted_count == 2
            assert task.status == "submitted"
            assert task.qa_queue_id is not None
            qa_count = db.query(Queue).filter(Queue.source_production_queue_id == qid).count()
            assert qa_count == 1, "exactly one QA queue even though two submits finished the task together"
        finally:
            db.close()
    finally:
        _cleanup([qid], [u["id"] for u in users])


def test_duplicate_draft_requests_create_one_open_row():
    suffix = uuid.uuid4().hex[:8]
    db = SessionLocal()
    users = _mk_users(db, 1, suffix)
    q = _mk_queue(db, suffix, n_tasks=1, required=3)
    qid = q.id
    task_id = db.query(Task.id).filter(Task.queue_id == qid).scalar()
    db.close()
    u = users[0]
    try:
        def draft(s):
            task = crud.get_task(s, str(task_id))
            crud.upsert_draft(s, task, u, {"data_type": "general_text"}, 5)
            return True

        results = _run_parallel([draft, draft, draft, draft])
        errors = [r for r in results if isinstance(r, Exception)]
        assert not errors, errors
        db = SessionLocal()
        try:
            n = (
                db.query(TaskAnnotation)
                .filter(TaskAnnotation.task_id == task_id, TaskAnnotation.status.in_(("draft", "returned")))
                .count()
            )
            assert n == 1
        finally:
            db.close()
    finally:
        _cleanup([qid], [u["id"] for u in users])


def _make_submitted_task(db, suffix: str, required: int = 1):
    """A production task already submitted by `required` annotators, routed to QA."""
    users = _mk_users(db, required, suffix)
    q = _mk_queue(db, suffix, n_tasks=3, required=required)
    for t in db.query(Task).filter(Task.queue_id == q.id).all():
        for u in users:
            task = crud.get_task(db, str(t.id))
            assert crud.submit_annotation(db, task, u, dict(ANNOTATION), 10) == []
    db.refresh(q)
    return q, users


def test_qa_claims_hand_each_task_to_one_reviewer():
    suffix = uuid.uuid4().hex[:8]
    db = SessionLocal()
    q, annotators = _make_submitted_task(db, suffix)
    reviewers = _mk_users(db, 5, suffix + "r")
    qa_id = q.linked_qa_queue_id
    db.close()
    assert qa_id is not None
    try:
        results = _run_parallel([(lambda u: (lambda s: crud.claim_next_qa_task(s, qa_id, u, None)))(u) for u in reviewers])
        errors = [r for r in results if isinstance(r, Exception)]
        assert not errors, errors
        got = [r["task_id"] for r in results if r and r.get("task_id")]
        assert len(got) == 3, results
        assert len(set(got)) == 3, "no task handed to two reviewers"
        db = SessionLocal()
        try:
            owners = db.query(Task.qa_owner_id).filter(Task.qa_queue_id == qa_id).all()
            assert all(o[0] is not None for o in owners)
            assert len({o[0] for o in owners}) == 3
        finally:
            db.close()
    finally:
        _cleanup([q.id], [u["id"] for u in annotators + reviewers])


def test_qa_finalize_vs_return_has_exactly_one_winner():
    suffix = uuid.uuid4().hex[:8]
    db = SessionLocal()
    q, annotators = _make_submitted_task(db, suffix)
    reviewers = _mk_users(db, 2, suffix + "r")
    task_id = db.query(Task.id).filter(Task.queue_id == q.id).order_by(Task.sequence).first()[0]
    db.close()
    ra, rb = reviewers
    try:
        def finalize(s):
            task = crud.get_task(s, str(task_id))
            return ("finalize", crud.finalize_task(s, task, ra, dict(ANNOTATION), "ok"))

        def do_return(s):
            task = crud.get_task(s, str(task_id))
            crud.return_task(s, task, "please recheck", rb)
            return ("return", None)

        results = _run_parallel([finalize, do_return])
        winners = [r for r in results if not isinstance(r, Exception)]
        losers = [r for r in results if isinstance(r, Exception)]
        assert len(winners) == 1, results
        assert len(losers) == 1 and isinstance(losers[0], ConflictError), results

        db = SessionLocal()
        try:
            task = crud.get_task(db, str(task_id))
            if winners[0][0] == "finalize":
                assert task.status == "approved" and task.qa_queue_id is not None and task.final_record
            else:
                assert task.status == "returned" and task.qa_queue_id is None and task.final_record is None
                assert all(a.status == "returned" for a in task.annotations)
        finally:
            db.close()
    finally:
        _cleanup([q.id], [u["id"] for u in annotators + reviewers])


def test_expired_claim_frees_the_slot_and_is_purged():
    suffix = uuid.uuid4().hex[:8]
    db = SessionLocal()
    users = _mk_users(db, 2, suffix)
    q = _mk_queue(db, suffix, n_tasks=1, required=1)
    qid = q.id
    a, b = users
    try:
        first = crud.claim_next_task(db, qid, a, None)
        assert first is not None
        # The only slot is taken: b gets nothing while a's lease is live.
        assert crud.claim_next_task(db, qid, b, None) is None
        # a walks away: backdate the lease beyond CLAIM_LEASE_SECONDS.
        stale = datetime.now(UTC) - timedelta(seconds=settings.CLAIM_LEASE_SECONDS + 120)
        db.query(TaskAnnotation).filter(TaskAnnotation.task_id == uuid.UUID(first)).update(
            {"last_seen_at": stale, "updated_at": stale, "created_at": stale}, synchronize_session=False
        )
        db.commit()
        second = crud.claim_next_task(db, qid, b, None)
        assert second == first, "the expired claim no longer blocks the task"
        rows = db.query(TaskAnnotation).filter(TaskAnnotation.task_id == uuid.UUID(first)).all()
        assert [str(r.user_id) for r in rows] == [b["id"]], "a's empty expired claim was purged"
    finally:
        db.close()
        _cleanup([qid], [u["id"] for u in users])
