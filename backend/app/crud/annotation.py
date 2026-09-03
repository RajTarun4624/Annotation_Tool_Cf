"""Annotation-workspace CRUD (SPEC2 section 5.3) - concurrency-safe edition.

Model (SageMaker Ground Truth style):
- Every task needs ``required_annotators`` RESPONSES (``TaskAnnotation`` rows);
  the same annotator may answer more than once, but holds at most ONE open
  (draft / returned) response per task (partial unique index).
- Work is handed out by a CLAIM: ``claim_next_task`` picks and reserves a task
  in one transaction under ``SELECT ... FOR UPDATE SKIP LOCKED``. The claim is
  an empty draft row whose ``last_seen_at`` the workspace heartbeats. A claim
  older than ``CLAIM_LEASE_SECONDS`` is a LEASE that expired: it no longer
  counts toward the task's load and, when empty, is purged - an abandoned tab
  never hides a task from others.
- Every write that changes what others may do (draft creation, submit, QA
  draft/finalize/return) re-checks its precondition under a row lock and
  raises ``ConflictError`` (HTTP 409) when someone else got there first.
- QA tasks carry an owner lease (``qa_owner_id`` / ``qa_owner_seen_at``); a
  reviewer may only save/finalize/return a task they hold (or whose lease
  expired).

All functions take an open ``Session`` and commit themselves when they write.
Serialisers return plain dicts shaped exactly like the SPEC2 payloads.
"""

from __future__ import annotations

import random
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, case, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased, selectinload

from app.core.config import settings
from app.core.errors import ConflictError
from app.core.taxonomy import length_bucket
from app.crud.queue import get_queue_by_id
from app.models import TaskAnnotation, TaskOutput
from app.models.queue import Queue
from app.models.task import Task
from app.models.user import User
from app.services.consensus import (
    build_record,
    compute_consensus,
    normalise_annotation,
    validate_annotation,
)

PREVIEW_CHARS = 140

# Task statuses in which an annotator can no longer touch their annotation.
LOCKED_TASK_STATUSES = ("submitted", "approved")
OPEN_STATUSES = ("draft", "returned")

# How many candidates a claim tries per round (each try is one short
# transaction; SKIP LOCKED makes contention cheap) and how many rounds it
# re-ranks when every candidate was locked by a concurrent claimant.
CLAIM_ATTEMPTS = 25
CLAIM_ROUNDS = 4

A = TaskAnnotation  # short alias for the aggregate expressions below


# ─── Helpers ───────────────────────────────────────────────────────────────

def _parse_uuid(value: Any) -> uuid.UUID | None:
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


def _now() -> datetime:
    return datetime.now(UTC)


def _lease_cutoff(now: datetime | None = None) -> datetime:
    """Claims / QA leases last touched before this instant are expired."""
    return (now or _now()) - timedelta(seconds=max(60, int(settings.CLAIM_LEASE_SECONDS or 600)))


def _user_name(user: dict[str, Any]) -> str:
    return str(user.get("full_name") or "")


def _preview(text_: str | None, limit: int = PREVIEW_CHARS) -> str:
    """First ``limit`` characters of the prompt collapsed onto one line."""
    if not text_:
        return ""
    single = " ".join(str(text_).split())
    return single[:limit]


def _sort_key(ann: TaskAnnotation) -> tuple:
    # submitted_at first (nulls last), then created_at, then id for stability.
    return (
        ann.submitted_at is None,
        ann.submitted_at or datetime.min,
        ann.created_at or datetime.min,
        str(ann.id),
    )


def submitted_annotations(task: Task) -> list[TaskAnnotation]:
    """Annotations that count towards consensus, ordered by submission time.

    ``returned`` annotations are included too: after a QA return the data is
    kept, so the QA/admin view can still show what was submitted before.
    """
    rows = [
        a for a in (task.annotations or [])
        if a.status in ("submitted", "returned") and a.data
    ]
    return sorted(rows, key=_sort_key)


def my_status_for(ann: TaskAnnotation | None) -> str:
    if ann is None:
        return "not_started"
    if ann.status == "submitted":
        return "submitted"
    if ann.status == "returned":
        return "returned"
    if ann.status == "declined":
        return "declined"
    return "draft"


def is_editable(task: Task, ann: TaskAnnotation | None) -> bool:
    if task.status in LOCKED_TASK_STATUSES:
        return False
    return ann is None or ann.status in OPEN_STATUSES


# ─── Loaders ───────────────────────────────────────────────────────────────

def get_task(db: Session, task_id: str) -> Task | None:
    """Task with its annotations + queue eagerly loaded, or None."""
    task_uuid = _parse_uuid(task_id)
    if task_uuid is None:
        return None
    return (
        db.query(Task)
        .options(selectinload(Task.annotations), selectinload(Task.queue))
        .filter(Task.id == task_uuid)
        .first()
    )


def get_queue(db: Session, queue_id: str) -> Queue | None:
    queue_uuid = _parse_uuid(queue_id)
    if queue_uuid is None:
        return None
    return db.query(Queue).filter(Queue.id == queue_uuid).first()


def _lock_task(db: Session, task_id: uuid.UUID, *, skip_locked: bool = False) -> Task | None:
    """Re-read the task row under ``FOR UPDATE`` (current committed state) and
    drop the cached annotations so the next access reloads them. Returns None
    when the row is gone or (with ``skip_locked``) held by someone else."""
    task = (
        db.query(Task)
        .filter(Task.id == task_id)
        .with_for_update(skip_locked=skip_locked)
        .populate_existing()
        .first()
    )
    if task is not None:
        db.expire(task, ["annotations"])
    return task


def _lock_queue(db: Session, queue_id: uuid.UUID) -> Queue | None:
    return db.query(Queue).filter(Queue.id == queue_id).with_for_update().populate_existing().first()


def my_annotations(task: Task, user_id: str) -> list[TaskAnnotation]:
    """Every response the user has on this task (submitted, declined, open)."""
    uid = _parse_uuid(user_id)
    return [a for a in (task.annotations or []) if a.user_id == uid]


def get_my_annotation(task: Task, user_id: str) -> TaskAnnotation | None:
    """The user's OPEN response on this task (draft / returned), or None.
    Submitted and declined responses are history and never block a new one."""
    for ann in my_annotations(task, user_id):
        if (ann.status or "draft") in OPEN_STATUSES:
            return ann
    return None


def my_submitted_count(task: Task, user_id: str) -> int:
    return sum(1 for a in my_annotations(task, user_id) if (a.status or "") == "submitted")


def i_declined(task: Task, user_id: str) -> bool:
    return any((a.status or "") == "declined" for a in my_annotations(task, user_id))


def required_annotators_for(queue: Queue | None) -> int:
    if queue is None:
        return 1
    return int(getattr(queue, "required_annotators", None) or 1)


def _user_dict(db: Session, user: dict[str, Any] | str) -> dict[str, Any]:
    """Accept a profile dict or a bare user id (legacy callers)."""
    if isinstance(user, dict):
        return user
    uid = _parse_uuid(user)
    row = db.query(User.id, User.full_name).filter(User.id == uid).first() if uid else None
    return {"id": str(uid) if uid else "", "full_name": (row.full_name if row else "") or ""}


# ─── Serialisers ───────────────────────────────────────────────────────────

def serialize_task_block(task: Task, queue: Queue | None = None) -> dict[str, Any]:
    """The ``task`` block shared by the production and QA workspace payloads."""
    queue = queue or task.queue
    text_ = task.input_text or ""
    return {
        "id": str(task.id),
        "queue_id": str(task.queue_id),
        "queue_name": (queue.name if queue else None) or "",
        "sequence": int(task.sequence or 0),
        "dataset": task.dataset or "",
        "input_text": text_,
        "data_length_chars": len(text_),
        "data_length_bucket": length_bucket(len(text_)),
        "meta_data": task.meta_data if isinstance(task.meta_data, dict) else {},
        "status": task.status or "pending",
        "source": task.source or "real_user",
        "submitted_count": int(task.submitted_count or 0),
        "required_annotators": required_annotators_for(queue),
        "qa_notes": task.qa_notes or "",
        "qa_queue_id": str(task.qa_queue_id) if task.qa_queue_id else None,
    }


def serialize_qa_task_block(task: Task, queue: Queue | None = None) -> dict[str, Any]:
    block = serialize_task_block(task, queue)
    block["finalized_by_name"] = task.finalized_by_name or None
    block["finalized_at"] = task.finalized_at
    block["qa_owner_id"] = str(task.qa_owner_id) if task.qa_owner_id else None
    return block


def serialize_my_annotation(ann: TaskAnnotation | None) -> dict[str, Any] | None:
    if ann is None:
        return None
    return {
        "status": ann.status or "draft",
        "data": ann.data if isinstance(ann.data, dict) else {},
        "elapsed_seconds": int(ann.elapsed_seconds or 0),
        "submitted_at": ann.submitted_at,
        "updated_at": ann.updated_at or ann.created_at,
    }


def task_payload(task: Task, user_id: str) -> dict[str, Any]:
    """Response of GET /workspace/tasks/{id} (also returned by draft/submit)."""
    mine = get_my_annotation(task, user_id)
    return {
        "task": serialize_task_block(task),
        "my_annotation": serialize_my_annotation(mine),
        "my_submissions": my_submitted_count(task, user_id),
        "editable": is_editable(task, mine) and not i_declined(task, user_id),
    }


def save_ack(task: Task, user_id: str) -> dict[str, Any]:
    """Slim response for autosave: everything the workspace repaints after a
    save, without the prompt text (which the client already has)."""
    mine = get_my_annotation(task, user_id)
    return {
        "task_id": str(task.id),
        "status": task.status or "pending",
        "submitted_count": int(task.submitted_count or 0),
        "my_annotation": serialize_my_annotation(mine),
        "editable": is_editable(task, mine) and not i_declined(task, user_id),
    }


def _consensus_for(task: Task, annotations: list[TaskAnnotation]) -> dict[str, Any]:
    if not annotations:
        return {"majority": {}, "agreement": {}, "consensus_reached": False}
    result = compute_consensus(task, annotations)
    return {
        "majority": result.get("majority") or {},
        "agreement": result.get("agreement") or {},
        "consensus_reached": bool(result.get("consensus_reached")),
    }


def _record_or_none(task: Task, annotations: list[TaskAnnotation], final: dict[str, Any]) -> dict | None:
    if not final:
        return None
    return build_record(task, annotations, final)


def agreement_level(agreement: dict[str, Any]) -> str | None:
    """Collapse the per-field agreement dict into one badge level for lists:
    "full" when every customer key is full, "split" when any is none,
    otherwise "majority". None when there is nothing to compare."""
    if not agreement:
        return None
    levels = [v for k, v in agreement.items() if k != "consensus_reached"]
    if not levels:
        return None
    if any(v == "split" for v in levels):
        return "split"
    if all(v == "full" for v in levels):
        return "full"
    return "majority"


def qa_draft_of(task: Task, user_id: str | None = None) -> dict[str, Any] | None:
    """The reviewer's saved-but-not-finalised QA form (``tasks.draft_data``),
    or None. When ``user_id`` is given only that reviewer's own draft is
    returned - another reviewer's partial work is never pre-filled."""
    d = task.draft_data if isinstance(task.draft_data, dict) else None
    if not d or not isinstance(d.get("data"), dict):
        return None
    if user_id and str(d.get("user_id") or "") != str(user_id):
        return None
    return {
        "data": d.get("data") or {},
        "qa_notes": str(d.get("qa_notes") or ""),
        "elapsed_seconds": int(d.get("elapsed_seconds") or 0),
        "user_id": str(d.get("user_id") or ""),
        "user_name": str(d.get("user_name") or ""),
        "updated_at": d.get("updated_at"),
    }


def qa_task_payload(task: Task, user_id: str | None = None) -> dict[str, Any]:
    """Response of GET /workspace/qa/tasks/{id} (also returned by finalize)."""
    annotations = submitted_annotations(task)
    consensus = _consensus_for(task, annotations)
    final = task.final_data if isinstance(task.final_data, dict) and task.final_data else consensus["majority"]

    if task.status == "approved" and isinstance(task.final_record, dict) and task.final_record:
        record = task.final_record
    else:
        record = _record_or_none(task, annotations, final)

    return {
        "task": serialize_qa_task_block(task),
        "annotations": [
            {
                "slot": idx,
                "id": str(a.id),
                "user_id": str(a.user_id) if a.user_id else None,
                "user_name": a.user_name or "",
                "status": a.status or "submitted",
                "submitted_at": a.submitted_at,
                "elapsed_seconds": int(a.elapsed_seconds or 0),
                "data": a.data if isinstance(a.data, dict) else {},
                "output": _derive_output(a.data),
            }
            for idx, a in enumerate(annotations, 1)
        ],
        "majority": consensus["majority"],
        "agreement": consensus["agreement"],
        "agreement_level": agreement_level(consensus["agreement"]),
        "consensus_reached": consensus["consensus_reached"],
        "final": final,
        "record": record,
        "qa_draft": qa_draft_of(task, user_id),
        "editable": task.status == "submitted",
    }


def _derive_output(data: Any) -> dict[str, bool]:
    types = data.get("attack_type") if isinstance(data, dict) else None
    types = types if isinstance(types, list) else []
    return {
        "jailbreak": "jailbreak" in types,
        "prompt_injection": "prompt_injection" in types,
        "prompt_leakage": "prompt_leakage" in types,
    }


# ─── Load / lease expressions (all evaluated in SQL) ───────────────────────

def _seen_expr(a=None):
    a = a if a is not None else A
    return func.coalesce(a.last_seen_at, a.updated_at, a.created_at)


def _live_other_draft_cond(a, uid: uuid.UUID | None, cutoff: datetime):
    """``a`` is a LIVE draft held by someone else that reserves a slot.

    An expired draft (lease older than ``cutoff``) counts for nobody. A REPEAT
    draft (its owner already submitted a response on this task) never
    reserves a slot: distinct annotators always take precedence, and a repeat
    that loses the race is refused at submit time instead."""
    S = aliased(TaskAnnotation)
    repeat = (
        select(S.id)
        .where(S.task_id == a.task_id, S.user_id == a.user_id, S.status == "submitted")
        .correlate(a)
        .exists()
    )
    return and_(a.status == "draft", a.user_id != uid, _seen_expr(a) > cutoff, ~repeat)


def _task_load(db: Session, task: Task, uid: uuid.UUID | None, cutoff: datetime) -> int:
    """Responses in flight on ONE task (caller holds the row lock): the
    maintained ``submitted_count`` plus live drafts held by others."""
    live = int(
        db.query(func.count(A.id))
        .filter(A.task_id == task.id, _live_other_draft_cond(A, uid, cutoff))
        .scalar()
        or 0
    )
    return int(task.submitted_count or 0) + live


def _pool_base(db: Session, queue_id: uuid.UUID, uid: uuid.UUID | None, cutoff: datetime):
    """Grouped query over the queue's UNLOCKED tasks with, per task: load
    (submitted_count + live drafts by others), and the caller's relation to it
    (open draft / submitted / declined). Both joins are pre-filtered (live
    drafts are few; the caller's rows are few), so the work is one indexed
    scan of the queue's tasks - independent of how many annotators are online
    and of how many responses exist."""
    A_live = aliased(TaskAnnotation)
    A_me = aliased(TaskAnnotation)
    load = func.coalesce(Task.submitted_count, 0) + func.count(func.distinct(A_live.id))
    mine_open = func.coalesce(func.bool_or(A_me.status.in_(OPEN_STATUSES)), False)
    mine_sub = func.coalesce(func.bool_or(A_me.status == "submitted"), False)
    declined = func.coalesce(func.bool_or(A_me.status == "declined"), False)
    return (
        db.query(
            Task.id.label("id"),
            Task.sequence.label("sequence"),
            load.label("load"),
            mine_open.label("mine_open"),
            mine_sub.label("mine_sub"),
            declined.label("declined"),
        )
        .select_from(Task)
        .outerjoin(A_live, and_(A_live.task_id == Task.id, _live_other_draft_cond(A_live, uid, cutoff)))
        .outerjoin(A_me, and_(A_me.task_id == Task.id, A_me.user_id == uid))
        .filter(Task.queue_id == queue_id, Task.status.notin_(LOCKED_TASK_STATUSES))
        .group_by(Task.id, Task.sequence, Task.submitted_count)
    )


def _pool_window(db, queue_id: uuid.UUID, uid: uuid.UUID | None, cutoff: datetime, required: int, limit: int = 60):
    """The best ``limit`` candidates, ranked in SQL: the caller's own open
    draft first, then tasks still below the cap, never-answered before
    answer-again, MOST-loaded first (finish a task's N responses before
    starting new ones - the Ground Truth rule that keeps QA fed), and a
    SHUFFLE among tasks at the same level so annotators do not all walk the
    queue in the same order. Declined tasks are excluded."""
    sub = _pool_base(db, queue_id, uid, cutoff).subquery("pool")
    fresh = and_(~sub.c.mine_sub, ~sub.c.mine_open)
    return (
        db.query(sub.c.id, sub.c.sequence, sub.c.load, sub.c.mine_open, sub.c.mine_sub, sub.c.declined)
        .filter(~sub.c.declined)
        .order_by(
            sub.c.mine_open.desc(),
            (sub.c.load < required).desc(),
            fresh.desc(),
            sub.c.load.desc(),
            func.random(),
        )
        .limit(limit)
        .all()
    )


def _pool_counts(db, queue_id: uuid.UUID, uid: uuid.UUID | None, cutoff: datetime, required: int) -> tuple[int, int]:
    """(available, resumable) for the caller, computed in SQL."""
    sub = _pool_base(db, queue_id, uid, cutoff).subquery("pool")
    row = (
        db.query(
            func.count(case((and_(~sub.c.declined, sub.c.load < required), 1))).label("available"),
            func.count(case((sub.c.mine_open, 1))).label("resumable"),
        )
        .one()
    )
    return int(row.available or 0), int(row.resumable or 0)


def purge_expired_claims(db: Session, queue_id: uuid.UUID, cutoff: datetime) -> int:
    """Delete EMPTY drafts whose lease expired (the annotator opened the task
    and walked away). Drafts with answers are kept - they simply stop counting
    as load until their owner comes back. Tasks left without any response go
    back to ``pending``. Commits."""
    stale = (
        db.query(A.id)
        .join(Task, Task.id == A.task_id)
        .filter(
            Task.queue_id == queue_id,
            A.status == "draft",
            text("coalesce(task_annotations.data, '{}'::jsonb) = '{}'::jsonb"),
            _seen_expr() < cutoff,
        )
    )
    ids = [row.id for row in stale.all()]
    if not ids:
        return 0
    db.query(A).filter(A.id.in_(ids)).delete(synchronize_session=False)
    db.execute(
        text(
            "UPDATE tasks SET status = 'pending', started_at = NULL "
            "WHERE queue_id = :q AND status = 'active' "
            "AND NOT EXISTS (SELECT 1 FROM task_annotations a WHERE a.task_id = tasks.id)"
        ),
        {"q": str(queue_id)},
    )
    db.commit()
    return len(ids)


# ─── Production workspace ──────────────────────────────────────────────────

def list_workspace_tasks(db: Session, queue: Queue, user_id: str) -> dict[str, Any]:
    """Payload of GET /workspace/queues/{id} for one annotator.

    Metadata only - the prompt column is never loaded here; the single-task
    endpoint is the only place that reads it."""
    uid = _parse_uuid(user_id)
    tasks = (
        db.query(
            Task.id, Task.sequence, Task.dataset, Task.status, Task.submitted_count,
            func.left(func.coalesce(Task.input_text, ""), PREVIEW_CHARS * 2).label("preview_src"),
        )
        .filter(Task.queue_id == queue.id)
        .order_by(Task.sequence.asc(), Task.created_at.asc(), Task.id.asc())
        .all()
    )
    mine_by_task: dict[uuid.UUID, str] = {}   # my OPEN response status per task
    my_subs: dict[uuid.UUID, int] = {}
    my_declined: set[uuid.UUID] = set()
    if tasks and uid is not None:
        rows = (
            db.query(A.task_id, A.status)
            .join(Task, Task.id == A.task_id)
            .filter(Task.queue_id == queue.id, A.user_id == uid)
            .all()
        )
        for task_id, st in rows:
            st = st or "draft"
            if st in OPEN_STATUSES:
                mine_by_task[task_id] = st
            elif st == "submitted":
                my_subs[task_id] = my_subs.get(task_id, 0) + 1
            elif st == "declined":
                my_declined.add(task_id)

    required = required_annotators_for(queue)
    items: list[dict[str, Any]] = []
    my_done = 0
    for t in tasks:
        open_status = mine_by_task.get(t.id)
        if open_status:
            status = "returned" if open_status == "returned" else "draft"
        elif t.id in my_declined:
            status = "declined"
        elif my_subs.get(t.id):
            status = "submitted"
        else:
            status = "not_started"
        my_done += my_subs.get(t.id, 0)
        items.append({
            "id": str(t.id),
            "sequence": int(t.sequence or 0),
            "dataset": t.dataset or "",
            "preview": _preview(t.preview_src),
            "status": t.status or "pending",
            "submitted_count": int(t.submitted_count or 0),
            "required_annotators": required,
            "my_status": status,
            "my_submissions": my_subs.get(t.id, 0),
        })

    queue_dict = get_queue_by_id(db, str(queue.id)) or {}
    return {"queue": queue_dict, "tasks": items, "my_done": my_done}


def workspace_queue_summary(db: Session, queue: Queue, user_id: str) -> dict[str, Any]:
    """Payload of GET /workspace/queues/{id}/summary: counts only (what the
    workspace needs to open), independent of the number of tasks."""
    uid = _parse_uuid(user_id)
    cutoff = _lease_cutoff()
    required = required_annotators_for(queue)
    available, resumable = _pool_counts(db, queue.id, uid, cutoff, required) if uid else (0, 0)
    my_done = int(
        db.query(func.count(A.id))
        .join(Task, Task.id == A.task_id)
        .filter(Task.queue_id == queue.id, A.user_id == uid, A.status == "submitted")
        .scalar()
        or 0
    ) if uid else 0
    queue_dict = get_queue_by_id(db, str(queue.id)) or {}
    return {
        "queue": queue_dict,
        "available": available,
        "resumable": resumable,
        "my_done": my_done,
        "required_annotators": required,
    }


def claim_next_task(
    db: Session,
    queue: Queue | uuid.UUID,
    user: dict[str, Any] | str,
    after_sequence: int | None = None,
) -> str | None:
    """Pick AND reserve the next task for the caller in one go.

    Pool = unlocked tasks the user has not declined whose responses in flight
    (submitted + live drafts by others) are below ``required_annotators``.
    The caller's own open draft is resumed first on Start Working; after a
    submit/skip/decline tasks they have never answered come first, then tasks
    they may answer again; the task closest to its N responses wins, ties are
    shuffled.

    The chosen row is locked with ``FOR UPDATE SKIP LOCKED``, its load is
    re-counted under the lock, and the claim (an empty draft with a fresh
    lease) is inserted before commit - two annotators can never be handed the
    same last slot. Returns the task id or None when nothing is available.
    """
    profile = _user_dict(db, user)
    uid = _parse_uuid(profile.get("id"))
    if uid is None:
        return None
    queue_obj = queue if isinstance(queue, Queue) else db.query(Queue).filter(Queue.id == queue).first()
    if queue_obj is None:
        return None
    now = _now()
    cutoff = _lease_cutoff(now)
    purge_expired_claims(db, queue_obj.id, cutoff)
    required = required_annotators_for(queue_obj)

    # A candidate row that is locked by another claimant is skipped (SKIP
    # LOCKED). If every candidate was skipped, those claims are mid-flight:
    # re-rank once they commit instead of telling the user nothing is left.
    for attempt in range(CLAIM_ROUNDS):
        # Ranked in SQL (own open draft, below-cap, never-answered, least-loaded,
        # queue order); only a small window comes back whatever the queue size.
        rows = _pool_window(db, queue_obj.id, uid, cutoff, required)
        if not rows:
            return None
        others = [r for r in rows if after_sequence is None or int(r.sequence or 0) != after_sequence]
        pool = others or rows

        # A task the caller already holds open (their own claim/draft) always
        # comes first - except the one they just left (after_sequence), which
        # is only offered again when nothing else is available.
        resumable = [r for r in pool if r.mine_open]
        if resumable:
            pick = resumable[0]
            touch_claim(db, pick.id, uid, now)
            return str(pick.id)

        pool = [r for r in pool if int(r.load or 0) < required]
        if not pool:
            return None
        fresh = [r for r in pool if not r.mine_sub and not r.mine_open]
        if fresh:
            pool = fresh
        # Most-loaded first so a task collects its N responses and moves to QA
        # before new tasks are opened; ties are shuffled so annotators spread
        # across the queue instead of all walking it in the same order.
        # Contention on the same row is absorbed by SKIP LOCKED.
        pool.sort(key=lambda r: (-int(r.load or 0), random.random()))

        skipped_locked = False
        for r in pool[:CLAIM_ATTEMPTS]:
            task = _lock_task(db, r.id, skip_locked=True)
            if task is None:
                db.rollback()
                skipped_locked = True
                continue
            if task.status in LOCKED_TASK_STATUSES or _task_load(db, task, uid, cutoff) >= required:
                db.rollback()
                continue
            existing = (
                db.query(A)
                .filter(A.task_id == task.id, A.user_id == uid, A.status.in_(OPEN_STATUSES))
                .first()
            )
            if existing is None:
                db.add(TaskAnnotation(
                    id=uuid.uuid4(),
                    task_id=task.id,
                    user_id=uid,
                    user_name=_user_name(profile),
                    status="draft",
                    data={},
                    elapsed_seconds=0,
                    submitted_at=None,
                    last_seen_at=now,
                    created_at=now,
                    updated_at=now,
                ))
            else:
                existing.last_seen_at = now
            if task.status in ("pending", "returned"):
                task.status = "active"
            if task.started_at is None:
                task.started_at = now
            task.updated_at = now
            try:
                db.commit()
            except IntegrityError:
                # My other tab claimed this very task a moment ago: it is mine either way.
                db.rollback()
            return str(task.id)
        if not skipped_locked:
            return None
        time.sleep(0.02 * (attempt + 1))
    return None


def next_task_id(
    db: Session, queue_id: uuid.UUID, user_id: str, after_sequence: int | None = None
) -> str | None:
    """Legacy signature kept for the admin task endpoints: claims like
    ``claim_next_task``."""
    return claim_next_task(db, queue_id, user_id, after_sequence)


def touch_claim(db: Session, task_id: uuid.UUID, uid: uuid.UUID | None, now: datetime | None = None) -> bool:
    """Heartbeat: extend the caller's lease on their open response. One UPDATE,
    no lock. Returns False when the caller holds no open response (the lease
    was purged or the task was submitted by others)."""
    if uid is None:
        return False
    n = (
        db.query(A)
        .filter(A.task_id == task_id, A.user_id == uid, A.status.in_(OPEN_STATUSES))
        .update({"last_seen_at": now or _now()}, synchronize_session=False)
    )
    db.commit()
    return bool(n)


def open_claims(task: Task, cutoff: datetime | None = None) -> list[dict[str, Any]]:
    """Admin view: who currently holds an open response on the task."""
    cut = cutoff or _lease_cutoff()
    out = []
    for a in task.annotations or []:
        if (a.status or "draft") not in OPEN_STATUSES:
            continue
        seen = a.last_seen_at or a.updated_at or a.created_at
        seen_cmp = seen.replace(tzinfo=UTC) if seen is not None and seen.tzinfo is None else seen
        out.append({
            "annotation_id": str(a.id),
            "user_id": str(a.user_id) if a.user_id else None,
            "user_name": a.user_name or "",
            "status": a.status or "draft",
            "has_answers": bool(a.data),
            "last_seen_at": seen,
            "live": bool(seen_cmp and seen_cmp > cut),
        })
    return out


def force_release_claim(db: Session, task: Task, target_user_id: str) -> int:
    """Admin: free a task held by another user. Empty drafts are deleted; drafts
    with answers are kept but their lease is expired so they stop counting as
    load (the owner can still resume and will be re-checked on submit)."""
    uid = _parse_uuid(target_user_id)
    if uid is None:
        return 0
    now = _now()
    task = _lock_task(db, task.id) or task
    n = 0
    for a in list(task.annotations or []):
        if a.user_id != uid or (a.status or "draft") not in OPEN_STATUSES:
            continue
        if not a.data:
            db.delete(a)
        else:
            a.last_seen_at = _lease_cutoff(now) - timedelta(seconds=1)
        n += 1
    remaining = [a for a in (task.annotations or []) if not (a.user_id == uid and not a.data and (a.status or "draft") in OPEN_STATUSES)]
    if not remaining and task.status == "active":
        task.status = "pending"
        task.started_at = None
    task.updated_at = now
    db.commit()
    return n


def skip_task(db: Session, task: Task, user: dict[str, Any]) -> None:
    """Skip: drop the caller's untouched claim (an empty draft created when the
    task was opened) so the task counts as free for everyone else. A draft with
    real answers is kept."""
    ann = get_my_annotation(task, user["id"])
    if ann is not None and ann.status == "draft" and not (ann.data or {}):
        release_task(db, task, user)


def upsert_draft(
    db: Session,
    task: Task,
    user: dict[str, Any],
    data: dict[str, Any],
    elapsed_seconds: int,
) -> TaskAnnotation:
    """Create or update the caller's draft under a row lock; task goes
    ``active`` if it was pending/returned. Creating a NEW response re-checks
    the load cap and raises ``ConflictError`` when the task is already full."""
    now = _now()
    uid = _parse_uuid(user["id"])
    task = _lock_task(db, task.id) or task
    if task.status in LOCKED_TASK_STATUSES:
        raise ConflictError("This task has already been completed by other annotators.")
    ann = get_my_annotation(task, user["id"])
    if ann is None:
        required = required_annotators_for(task.queue or get_queue(db, str(task.queue_id)))
        if _task_load(db, task, uid, _lease_cutoff(now)) >= required:
            raise ConflictError("This task already has all the responses it needs. You will be moved to another task.")
        ann = TaskAnnotation(
            id=uuid.uuid4(),
            task_id=task.id,
            user_id=uid,
            user_name=_user_name(user),
            status="draft",
            data=data if isinstance(data, dict) else {},
            elapsed_seconds=max(0, int(elapsed_seconds or 0)),
            submitted_at=None,
            last_seen_at=now,
            created_at=now,
            updated_at=now,
        )
        db.add(ann)
        task.annotations.append(ann)
    else:
        ann.status = "draft"  # returned -> draft as well
        ann.user_name = _user_name(user) or ann.user_name
        ann.data = data if isinstance(data, dict) else {}
        ann.elapsed_seconds = max(0, int(elapsed_seconds or 0))
        ann.last_seen_at = now
        ann.updated_at = now

    if task.status in ("pending", "returned"):
        task.status = "active"
    if task.started_at is None:
        task.started_at = now
    task.updated_at = now

    try:
        db.commit()
    except IntegrityError:
        # A concurrent request of the same user created the open row first:
        # apply this save onto that row instead.
        db.rollback()
        task = _lock_task(db, task.id) or task
        ann = get_my_annotation(task, user["id"])
        if ann is None:
            raise ConflictError("Your draft could not be saved. Please try again.")
        ann.data = data if isinstance(data, dict) else {}
        ann.elapsed_seconds = max(0, int(elapsed_seconds or 0))
        ann.last_seen_at = now
        ann.updated_at = now
        db.commit()
    db.refresh(task)
    return ann


def decline_task(
    db: Session,
    task: Task,
    user: dict[str, Any],
    reason: str = "",
) -> TaskAnnotation:
    """Mark the caller's annotation as declined with a reason."""
    now = _now()
    uid = _parse_uuid(user["id"])
    task = _lock_task(db, task.id) or task
    ann = get_my_annotation(task, user["id"])
    if ann is None:
        ann = next((a for a in my_annotations(task, user["id"]) if a.status == "declined"), None)
    if ann is None:
        ann = TaskAnnotation(
            id=uuid.uuid4(),
            task_id=task.id,
            user_id=uid,
            user_name=_user_name(user),
            status="declined",
            data={"declined": True, "reason": reason},
            created_at=now,
            updated_at=now,
        )
        db.add(ann)
        task.annotations.append(ann)
    else:
        ann.status = "declined"
        ann.user_name = _user_name(user) or ann.user_name
        ann.data = {"declined": True, "reason": reason}
        ann.updated_at = now

    task.declined_reason = reason or task.declined_reason
    task.updated_at = now
    db.commit()
    db.refresh(task)
    return ann


def release_task(db: Session, task: Task, user: dict[str, Any]) -> None:
    """Release/delete the caller's in-progress draft on this task.

    When that was the only annotation the task goes back to ``pending``
    (``active`` means >= 1 draft/submission) so nobody sees a phantom
    in-progress task."""
    now = _now()
    uid = _parse_uuid(user["id"])
    task = _lock_task(db, task.id) or task
    mine_open = [a for a in (task.annotations or []) if a.user_id == uid and (a.status or "draft") == "draft"]
    for a in mine_open:
        db.delete(a)
    remaining = [a for a in (task.annotations or []) if a not in mine_open]
    if not remaining and task.status == "active":
        task.status = "pending"
        task.started_at = None
    task.updated_at = now
    db.commit()
    db.refresh(task)


def ensure_qa_queue(db: Session, prod: Queue, created_by: uuid.UUID | None = None) -> Queue:
    """Return the production queue's linked QA queue, creating it lazily when
    it is missing. Locks the production queue row so two submits finishing the
    first task at the same instant create exactly one QA queue. Does NOT
    commit; the caller's transaction covers it."""
    prod = _lock_queue(db, prod.id) or prod
    if prod.linked_qa_queue_id:
        qa = db.query(Queue).filter(Queue.id == prod.linked_qa_queue_id).first()
        if qa is not None:
            return qa
    now = _now()
    qa = Queue(
        id=uuid.uuid4(),
        name=f"{prod.name} - QA",
        project_id=prod.project_id,
        task_name=prod.task_name,
        batch_name=prod.batch_name,
        annotation_type="qa",
        priority=prod.priority,
        sla_hours=prod.sla_hours,
        status="inactive",
        assigned_user_id=None,
        linked_qa_queue_id=None,
        source_production_queue_id=prod.id,
        timer_seconds=prod.timer_seconds,
        created_by=created_by or prod.created_by,
        created_at=now,
        updated_at=now,
    )
    qa.required_annotators = 1
    db.add(qa)
    db.flush()
    prod.linked_qa_queue_id = qa.id
    prod.updated_at = now
    return qa


def submit_annotation(
    db: Session,
    task: Task,
    user: dict[str, Any],
    data: dict[str, Any],
    elapsed_seconds: int,
) -> list[str]:
    """Validate + submit the caller's annotation under a row lock. Returns the
    validation error list (empty on success). Raises ``ConflictError`` when
    the task is already locked or already has every response it needs - the
    surplus answer is NOT stored. On success the task's submitted_count is
    refreshed and it moves to the QA queue once enough submissions exist."""
    errors = validate_annotation(data)
    if errors:
        return errors
    clean = normalise_annotation(data)

    now = _now()
    uid = _parse_uuid(user["id"])
    task = _lock_task(db, task.id) or task
    if task.status in LOCKED_TASK_STATUSES:
        raise ConflictError("This task was already completed by other annotators; your answer was not stored.")
    prod = task.queue or get_queue(db, str(task.queue_id))
    required = required_annotators_for(prod)
    ann = get_my_annotation(task, user["id"])
    others_query = db.query(func.count(A.id)).filter(A.task_id == task.id, A.status == "submitted")
    if ann is not None:
        others_query = others_query.filter(A.id != ann.id)
    if int(others_query.scalar() or 0) >= required:
        raise ConflictError("This task already has all the responses it needs; your answer was not stored. You will be moved to another task.")

    if ann is None:
        ann = TaskAnnotation(
            id=uuid.uuid4(),
            task_id=task.id,
            user_id=uid,
            user_name=_user_name(user),
            status="submitted",
            data=clean,
            elapsed_seconds=max(0, int(elapsed_seconds or 0)),
            submitted_at=now,
            last_seen_at=now,
            created_at=now,
            updated_at=now,
        )
        db.add(ann)
        task.annotations.append(ann)
    else:
        ann.status = "submitted"
        ann.user_name = _user_name(user) or ann.user_name
        ann.data = clean
        ann.elapsed_seconds = max(0, int(elapsed_seconds or 0))
        ann.submitted_at = now
        ann.last_seen_at = now
        ann.updated_at = now
    db.flush()

    # Record in tasks_output table
    derived = _derive_output(clean)
    sev = clean.get("severity") if isinstance(clean.get("severity"), dict) else {}
    out_row = (
        db.query(TaskOutput)
        .filter(TaskOutput.annotation_id == ann.id)
        .first()
    )
    if out_row is None:
        out_row = TaskOutput(
            id=uuid.uuid4(),
            annotation_id=ann.id,
            task_id=task.id,
            user_id=uid,
            user_name=_user_name(user),
            queue_id=task.queue_id,
            dataset=task.dataset or "",
            input_text=task.input_text or "",
            data_type=clean.get("data_type"),
            data_structure=clean.get("data_structure"),
            attack_type=clean.get("attack_type") or [],
            attack_subcategory=clean.get("attack_subcategory") or [],
            domain=clean.get("domain"),
            role=", ".join(clean.get("role") or []),
            verified=bool(clean.get("verified")),
            language=clean.get("language") or "en",
            document_edited=bool(clean.get("document_edited")),
            source_description=clean.get("source_description") or "",
            severity_j=int(sev.get("J") or 0),
            severity_i=int(sev.get("I") or 0),
            severity_l=int(sev.get("L") or 0),
            intention=clean.get("intention"),
            source=clean.get("source") or task.source or "real_user",
            jailbreak=derived["jailbreak"],
            prompt_injection=derived["prompt_injection"],
            prompt_leakage=derived["prompt_leakage"],
            annotation_data=clean,
            elapsed_seconds=max(0, int(elapsed_seconds or 0)),
            status="submitted",
            submitted_at=now,
            created_at=now,
            updated_at=now,
        )
        db.add(out_row)
    else:
        out_row.user_name = _user_name(user) or out_row.user_name
        out_row.dataset = task.dataset or out_row.dataset
        out_row.input_text = task.input_text or out_row.input_text
        out_row.data_type = clean.get("data_type")
        out_row.data_structure = clean.get("data_structure")
        out_row.attack_type = clean.get("attack_type") or []
        out_row.attack_subcategory = clean.get("attack_subcategory") or []
        out_row.domain = clean.get("domain")
        out_row.role = ", ".join(clean.get("role") or [])
        out_row.verified = bool(clean.get("verified"))
        out_row.language = clean.get("language") or "en"
        out_row.document_edited = bool(clean.get("document_edited"))
        out_row.source_description = clean.get("source_description") or ""
        out_row.severity_j = int(sev.get("J") or 0)
        out_row.severity_i = int(sev.get("I") or 0)
        out_row.severity_l = int(sev.get("L") or 0)
        out_row.intention = clean.get("intention")
        out_row.source = clean.get("source") or task.source or "real_user"
        out_row.jailbreak = derived["jailbreak"]
        out_row.prompt_injection = derived["prompt_injection"]
        out_row.prompt_leakage = derived["prompt_leakage"]
        out_row.annotation_data = clean
        out_row.elapsed_seconds = max(0, int(elapsed_seconds or 0))
        out_row.status = "submitted"
        out_row.submitted_at = now
        out_row.updated_at = now

    submitted = int(
        db.query(func.count(A.id))
        .filter(A.task_id == task.id, A.status == "submitted")
        .scalar()
        or 0
    )
    task.submitted_count = submitted

    if submitted >= required:
        task.status = "submitted"
        task.submitted_at = now
        if prod is not None:
            qa = ensure_qa_queue(db, prod, created_by=uid)
            task.qa_queue_id = qa.id
        # The task is full: other users' untouched claims are void now. Drop
        # them so nobody keeps a phantom "resume" on a locked task. Drafts with
        # answers are kept as history.
        db.query(A).filter(
            A.task_id == task.id,
            A.status == "draft",
            A.id != ann.id,
            text("coalesce(task_annotations.data, '{}'::jsonb) = '{}'::jsonb"),
        ).delete(synchronize_session=False)
    else:
        task.status = "active"
    if task.started_at is None:
        task.started_at = now
    task.updated_at = now

    db.commit()
    db.refresh(task)
    return []


# ─── QA workspace ──────────────────────────────────────────────────────────

def list_qa_tasks(db: Session, qa_queue: Queue, user_id: str | None = None) -> dict[str, Any]:
    """Payload of GET /workspace/qa/{qa_queue_id}. ``my_draft`` marks the task
    the calling reviewer holds (so the workspace resumes it first)."""
    uid = _parse_uuid(user_id)
    source = (
        db.query(Queue).filter(Queue.id == qa_queue.source_production_queue_id).first()
        if qa_queue.source_production_queue_id
        else None
    )
    tasks = (
        db.query(Task)
        .options(selectinload(Task.annotations))
        .filter(Task.qa_queue_id == qa_queue.id)
        .order_by(Task.sequence.asc(), Task.created_at.asc(), Task.id.asc())
        .all()
    )
    items: list[dict[str, Any]] = []
    for t in tasks:
        consensus_reached: bool | None = None
        level: str | None = None
        if t.status == "approved" and isinstance(t.final_record, dict):
            iaa = t.final_record.get("inter_annotator_agreement") or {}
            consensus_reached = bool(iaa.get("consensus_reached")) if iaa else None
            level = agreement_level({k: v for k, v in iaa.items() if k != "consensus_reached"})
        else:
            anns = submitted_annotations(t)
            if anns:
                consensus = _consensus_for(t, anns)
                consensus_reached = consensus["consensus_reached"]
                level = agreement_level(consensus["agreement"])
        items.append({
            "id": str(t.id),
            "sequence": int(t.sequence or 0),
            "dataset": t.dataset or "",
            "preview": _preview(t.input_text),
            "status": t.status or "submitted",
            "submitted_count": int(t.submitted_count or 0),
            "consensus_reached": consensus_reached,
            "agreement_level": level,
            "finalized_by_name": t.finalized_by_name or None,
            "finalized_at": t.finalized_at,
            "my_draft": bool(uid and t.status == "submitted" and t.qa_owner_id == uid),
        })

    queue_dict = get_queue_by_id(db, str(qa_queue.id)) or {}
    return {
        "queue": queue_dict,
        "source_queue": {
            "id": str(source.id) if source else None,
            "name": source.name if source else None,
            "required_annotators": required_annotators_for(source),
        },
        "tasks": items,
    }


def qa_queue_summary(db: Session, qa_queue: Queue, user_id: str | None = None) -> dict[str, Any]:
    """Counts only for opening the QA workspace: awaiting, held by me, held by
    others (live lease), reviewed."""
    uid = _parse_uuid(user_id)
    cutoff = _lease_cutoff()
    live_other = and_(Task.qa_owner_id.isnot(None), Task.qa_owner_id != uid, Task.qa_owner_seen_at > cutoff)
    row = (
        db.query(
            func.count(case((Task.status == "submitted", 1))).label("awaiting"),
            func.count(case((and_(Task.status == "submitted", Task.qa_owner_id == uid), 1))).label("mine"),
            func.count(case((and_(Task.status == "submitted", live_other), 1))).label("busy"),
            func.count(case((Task.status == "approved", 1))).label("approved"),
        )
        .filter(Task.qa_queue_id == qa_queue.id)
        .one()
    )
    source = (
        db.query(Queue).filter(Queue.id == qa_queue.source_production_queue_id).first()
        if qa_queue.source_production_queue_id
        else None
    )
    queue_dict = get_queue_by_id(db, str(qa_queue.id)) or {}
    return {
        "queue": queue_dict,
        "source_queue": {
            "id": str(source.id) if source else None,
            "name": source.name if source else None,
            "required_annotators": required_annotators_for(source),
        },
        "awaiting": int(row.awaiting or 0),
        "mine": int(row.mine or 0),
        "busy": int(row.busy or 0),
        "approved": int(row.approved or 0),
    }


def _qa_owned_by_other(db: Session, task_id: uuid.UUID, uid: uuid.UUID | None, cutoff: datetime) -> bool:
    """Evaluated in SQL so the lease comparison uses the same clock/timezone
    conversion as the write."""
    return bool(
        db.query(func.count(Task.id))
        .filter(
            Task.id == task_id,
            Task.qa_owner_id.isnot(None),
            Task.qa_owner_id != uid,
            Task.qa_owner_seen_at > cutoff,
        )
        .scalar()
    )


def _take_qa_lease(db: Session, task: Task, user: dict[str, Any], now: datetime) -> None:
    """Caller must hold the task row lock. Gives the task to ``user`` unless a
    different reviewer holds a live lease (ConflictError)."""
    uid = _parse_uuid(user["id"])
    if _qa_owned_by_other(db, task.id, uid, _lease_cutoff(now)):
        raise ConflictError("Another reviewer is working on this task right now. You will be moved to another task.")
    if task.qa_owner_id != uid:
        # A previous holder's partial draft is theirs; never pre-fill it for the new owner.
        d = task.draft_data if isinstance(task.draft_data, dict) else {}
        if str(d.get("user_id") or "") != str(uid):
            task.draft_data = {}
        task.qa_owner_id = uid
    task.qa_owner_seen_at = now


def claim_next_qa_task(
    db: Session,
    qa_queue: Queue | uuid.UUID | None,
    user: dict[str, Any] | str,
    after_sequence: int | None = None,
) -> dict[str, Any]:
    """Pick AND reserve a task awaiting review for the caller.

    Order: the caller's own held task first, then a task nobody holds (or
    whose holder's lease expired), avoiding the task just left. The chosen row
    is locked with ``FOR UPDATE SKIP LOCKED`` and the lease re-checked before
    the owner is written. Returns {"task_id", "busy"} where ``busy`` counts
    tasks currently held by other reviewers (so the UI can say why nothing
    was handed out)."""
    empty = {"task_id": None, "busy": 0}
    if qa_queue is None:
        return empty
    qa_queue_id = qa_queue.id if isinstance(qa_queue, Queue) else qa_queue
    profile = _user_dict(db, user)
    uid = _parse_uuid(profile.get("id"))
    if uid is None:
        return empty
    now = _now()
    cutoff = _lease_cutoff(now)
    live_other = case(
        (and_(Task.qa_owner_id.isnot(None), Task.qa_owner_id != uid, Task.qa_owner_seen_at > cutoff), True),
        else_=False,
    )
    rows = (
        db.query(Task.id, Task.sequence, Task.qa_owner_id, live_other.label("busy"))
        .filter(Task.qa_queue_id == qa_queue_id, Task.status == "submitted")
        .all()
    )
    if not rows:
        return empty
    busy_total = sum(1 for r in rows if r.busy)
    others = [r for r in rows if after_sequence is None or int(r.sequence or 0) != after_sequence]
    pool = others or rows

    mine = [r for r in pool if r.qa_owner_id == uid]
    if mine:
        pick = random.choice(mine)
        db.query(Task).filter(Task.id == pick.id, Task.qa_owner_id == uid).update(
            {"qa_owner_seen_at": now}, synchronize_session=False
        )
        db.commit()
        return {"task_id": str(pick.id), "busy": busy_total}

    free = [r for r in pool if not r.busy]
    random.shuffle(free)
    for r in free[:CLAIM_ATTEMPTS]:
        task = _lock_task(db, r.id, skip_locked=True)
        if task is None or task.status != "submitted":
            db.rollback()
            continue
        try:
            _take_qa_lease(db, task, profile, now)
        except ConflictError:
            db.rollback()
            continue
        task.updated_at = now
        db.commit()
        return {"task_id": str(task.id), "busy": busy_total}
    return {"task_id": None, "busy": busy_total}


def next_qa_task_id(
    db: Session, qa_queue_id: uuid.UUID | None, after_sequence: int | None = None, user_id: str | None = None
) -> str | None:
    """Legacy signature: claims like ``claim_next_qa_task``."""
    if not user_id:
        return None
    return claim_next_qa_task(db, qa_queue_id, user_id, after_sequence).get("task_id")


def touch_qa_lease(db: Session, task: Task, user: dict[str, Any]) -> bool:
    """QA heartbeat: extend the caller's lease; False when they no longer hold it."""
    uid = _parse_uuid(user["id"])
    n = (
        db.query(Task)
        .filter(Task.id == task.id, Task.qa_owner_id == uid, Task.status == "submitted")
        .update({"qa_owner_seen_at": _now()}, synchronize_session=False)
    )
    db.commit()
    return bool(n)


def save_qa_draft(
    db: Session,
    task: Task,
    user: dict[str, Any],
    data: dict[str, Any],
    qa_notes: str,
    elapsed_seconds: int,
) -> None:
    """Store the reviewer's in-progress final form (Save / Stop and resume).
    Requires the QA lease (taken here when free)."""
    now = _now()
    task = _lock_task(db, task.id) or task
    if task.status != "submitted":
        raise ConflictError("This task is no longer awaiting review.")
    _take_qa_lease(db, task, user, now)
    task.draft_data = {
        "data": data if isinstance(data, dict) else {},
        "qa_notes": qa_notes or "",
        "elapsed_seconds": max(0, int(elapsed_seconds or 0)),
        "user_id": str(user["id"]),
        "user_name": _user_name(user),
        "updated_at": now.isoformat(),
    }
    task.updated_at = now
    db.commit()
    db.refresh(task)


def release_qa_task(db: Session, task: Task, user: dict[str, Any] | None = None, *, force: bool = False) -> None:
    """Discard the caller's QA draft and lease; the task stays awaiting review.
    Another reviewer's live lease is left alone unless ``force`` (admin)."""
    now = _now()
    uid = _parse_uuid(user["id"]) if user else None
    task = _lock_task(db, task.id) or task
    if not force and task.qa_owner_id is not None and task.qa_owner_id != uid:
        if _qa_owned_by_other(db, task.id, uid, _lease_cutoff(now)):
            raise ConflictError("Another reviewer holds this task; nothing was released.")
    task.draft_data = {}
    task.qa_owner_id = None
    task.qa_owner_seen_at = None
    task.updated_at = now
    db.commit()
    db.refresh(task)


def preview_record(task: Task, data: dict[str, Any]) -> dict[str, Any]:
    annotations = submitted_annotations(task)
    return build_record(task, annotations, normalise_annotation(data))


def _maybe_complete_queues(db: Session, task: Task, now: datetime) -> None:
    """When every task of the source production queue is approved, mark both
    the production queue and its QA queue completed. Flushes first so the
    COUNT sees the task that was just approved in this transaction."""
    db.flush()
    prod = task.queue or get_queue(db, str(task.queue_id))
    if prod is None:
        return
    remaining = int(
        db.query(func.count(Task.id))
        .filter(Task.queue_id == prod.id, Task.status != "approved")
        .scalar()
        or 0
    )
    if remaining:
        return
    prod.status = "completed"
    prod.updated_at = now
    qa_id = task.qa_queue_id or prod.linked_qa_queue_id
    if qa_id:
        qa = db.query(Queue).filter(Queue.id == qa_id).first()
        if qa is not None:
            qa.status = "completed"
            qa.updated_at = now


def finalize_task(
    db: Session,
    task: Task,
    user: dict[str, Any],
    data: dict[str, Any],
    qa_notes: str = "",
) -> list[str]:
    """Validate + store the final annotation/record; task -> approved.
    Returns validation errors (empty on success). Runs under the task row
    lock: a task that is no longer awaiting review, or held by another
    reviewer, raises ``ConflictError``."""
    errors = validate_annotation(data)
    if errors:
        return errors
    clean = normalise_annotation(data)

    now = _now()
    task = _lock_task(db, task.id) or task
    if task.status != "submitted":
        raise ConflictError("This task was already reviewed by someone else.")
    _take_qa_lease(db, task, user, now)
    annotations = submitted_annotations(task)

    task.final_data = clean
    task.final_record = build_record(task, annotations, clean)
    task.status = "approved"
    task.finalized_by = _parse_uuid(user["id"])
    task.finalized_by_name = _user_name(user)
    task.finalized_at = now
    task.qa_notes = qa_notes or ""
    task.draft_data = {}
    task.qa_owner_id = None
    task.qa_owner_seen_at = None
    task.submitted_by = _user_name(user)
    task.updated_at = now
    _maybe_complete_queues(db, task, now)

    db.commit()
    db.refresh(task)
    return []


def return_task(db: Session, task: Task, qa_notes: str, user: dict[str, Any] | None = None) -> None:
    """Send a task back to the annotators: status returned, detached from the
    QA queue, every annotation flagged ``returned`` (data kept). Runs under
    the task row lock with the same lease rules as finalize."""
    now = _now()
    task = _lock_task(db, task.id) or task
    if task.status != "submitted":
        raise ConflictError("This task was already reviewed by someone else.")
    if user is not None:
        _take_qa_lease(db, task, user, now)
    task.status = "returned"
    task.qa_queue_id = None
    task.submitted_count = 0
    task.qa_notes = qa_notes or ""
    task.draft_data = {}
    task.qa_owner_id = None
    task.qa_owner_seen_at = None
    task.final_data = None
    task.final_record = None
    task.finalized_by = None
    task.finalized_by_name = None
    task.finalized_at = None
    task.updated_at = now
    for ann in task.annotations or []:
        ann.status = "returned"
        ann.updated_at = now
    db.commit()
    db.refresh(task)
