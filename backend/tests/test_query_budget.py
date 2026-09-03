"""Statement budgets for the hot paths (real PostgreSQL).

Every request an annotator makes many times a minute must issue a small,
FIXED number of SQL statements regardless of how many tasks the queue holds.
These tests count statements with a SQLAlchemy engine event so a future
change cannot quietly reintroduce a per-row query or a whole-queue load.

Run from ``backend/``::

    .venv/Scripts/python.exe -m pytest tests/test_query_budget.py -q
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager

import pytest
from sqlalchemy import event

from app.core.database import SessionLocal, engine, ensure_indexes, startup_lock
from app.crud import annotation as crud
from app.crud.queue import list_queues
from app.models import Queue, Task, User

from tests.test_concurrency import _cleanup, _mk_queue, _mk_users


@pytest.fixture(scope="module", autouse=True)
def _schema():
    with startup_lock():
        ensure_indexes()


@contextmanager
def count_statements():
    counter = {"n": 0}

    def _before(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        counter["n"] += 1

    event.listen(engine, "before_cursor_execute", _before)
    try:
        yield counter
    finally:
        event.remove(engine, "before_cursor_execute", _before)


@pytest.fixture(scope="module")
def big_queue():
    """One queue with 600 tasks, one annotator assigned to it (plus the
    standard 3-response requirement). Enough rows that any per-task query
    would blow the budget by two orders of magnitude."""
    suffix = uuid.uuid4().hex[:8]
    db = SessionLocal()
    users = _mk_users(db, 1, suffix)
    q = _mk_queue(db, suffix, n_tasks=600, required=3)
    user_row = db.query(User).filter(User.id == uuid.UUID(users[0]["id"])).one()
    q.assigned_users = [user_row]
    q.assigned_user_id = user_row.id
    db.commit()
    qid = q.id
    db.close()
    try:
        yield {"queue_id": qid, "user": users[0]}
    finally:
        _cleanup([qid], [users[0]["id"]])


def test_claim_uses_bounded_statements(big_queue):
    db = SessionLocal()
    try:
        with count_statements() as c:
            task_id = crud.claim_next_task(db, big_queue["queue_id"], big_queue["user"], None)
        assert task_id
        # purge (select+delete+update+commit) + pool aggregate + lock + recount + insert/commit
        assert c["n"] <= 14, f"claim issued {c['n']} statements"
    finally:
        db.close()


def test_heartbeat_is_one_update(big_queue):
    db = SessionLocal()
    try:
        task_id = crud.claim_next_task(db, big_queue["queue_id"], big_queue["user"], None)
        with count_statements() as c:
            assert crud.touch_claim(db, uuid.UUID(task_id), uuid.UUID(big_queue["user"]["id"]))
        assert c["n"] <= 3, f"heartbeat issued {c['n']} statements"
    finally:
        db.close()


def test_draft_save_is_bounded(big_queue):
    db = SessionLocal()
    try:
        task_id = crud.claim_next_task(db, big_queue["queue_id"], big_queue["user"], None)
        task = crud.get_task(db, task_id)
        with count_statements() as c:
            crud.upsert_draft(db, task, big_queue["user"], {"data_type": "general_text"}, 5)
        assert c["n"] <= 10, f"draft save issued {c['n']} statements"
    finally:
        db.close()


def test_queue_summary_is_bounded(big_queue):
    db = SessionLocal()
    try:
        queue = db.query(Queue).filter(Queue.id == big_queue["queue_id"]).one()
        with count_statements() as c:
            payload = crud.workspace_queue_summary(db, queue, big_queue["user"]["id"])
        assert payload["available"] >= 1
        assert c["n"] <= 10, f"summary issued {c['n']} statements"
    finally:
        db.close()


def test_my_queues_list_is_bounded(big_queue):
    db = SessionLocal()
    try:
        with count_statements() as c:
            items, total, _, _ = list_queues(
                db, assigned_user_id=big_queue["user"]["id"], hide_exhausted=True, page=1, page_size=25
            )
        assert total >= 1
        # queues + assigned users + project names + counts x2 + per-user view x4
        assert c["n"] <= 12, f"my-queues list issued {c['n']} statements"
    finally:
        db.close()


def test_workspace_list_never_loads_prompt_column(big_queue):
    """The legacy list endpoint must not pull the prompt text into Python."""
    db = SessionLocal()
    try:
        queue = db.query(Queue).filter(Queue.id == big_queue["queue_id"]).one()
        captured: list[str] = []

        def _before(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
            captured.append(statement)

        event.listen(engine, "before_cursor_execute", _before)
        try:
            payload = crud.list_workspace_tasks(db, queue, big_queue["user"]["id"])
        finally:
            event.remove(engine, "before_cursor_execute", _before)
        assert len(payload["tasks"]) == 600
        task_selects = [s for s in captured if "FROM tasks" in s and "left(" in s.lower()]
        assert task_selects, "expected the narrow left(input_text) projection"
        assert not any("tasks.input_text AS" in s for s in captured), "full prompt column was selected"
    finally:
        db.close()
