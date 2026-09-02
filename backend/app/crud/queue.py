"""Queue CRUD for the Prompt Attack Annotation Platform (SPEC2 §5.1).

Tasks live ONLY in the relational ``tasks`` table and always belong to their
PRODUCTION queue (``Task.queue_id``). A QA queue never owns tasks: a task
"moves" to QA by having ``Task.qa_queue_id`` set once enough annotators have
submitted, so QA counters are computed over ``Task.qa_queue_id``.

Every aggregate a queue response carries is computed with grouped queries
over ``Task`` (and ``TaskAnnotation`` for the per-user figures) so listing a
page of queues costs a fixed number of statements regardless of task volume.
"""

import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import case, func
from sqlalchemy.orm import Session, joinedload, selectinload

from app.models import TaskAnnotation
from app.models.project import Project
from app.models.queue import Queue, queue_assigned_users
from app.models.task import Task
from app.models.user import User
from app.schemas.pagination import paginate_query


MAX_TASKS_PER_QUEUE = 5000
DEFAULT_TIMER_SECONDS = 7200
DEFAULT_REQUIRED_ANNOTATORS = 3
INPUT_PREVIEW_CHARS = 140

# Status buckets used by the counters / summaries.
# Production queue: pending (no submission) · active (some work) · submitted
# (awaiting QA) · approved (finalised) · returned (QA sent back). The legacy
# names are still counted so an old row never disappears from the totals.
SUBMITTED_STATUSES = ("submitted",)
PENDING_STATUSES = ("pending",)
QA_AWAITING_STATUSES = ("submitted",)
QA_DONE_STATUSES = ("approved",)

_EMPTY_COUNTS: dict[str, int] = {
    "total": 0,
    "pending": 0,
    "active": 0,
    "submitted": 0,
    "approved": 0,
    "rejected": 0,
    "declined": 0,
    "skipped": 0,
    "returned": 0,
    "qa_total": 0,
    "qa_submitted": 0,
    "qa_approved": 0,
}

_WHITESPACE_RE = re.compile(r"\s+")


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


def input_preview(text: str | None, limit: int = INPUT_PREVIEW_CHARS) -> str:
    """First ``limit`` characters of the prompt collapsed onto one line."""
    if not text:
        return ""
    flat = _WHITESPACE_RE.sub(" ", str(text)).strip()
    if len(flat) <= limit:
        return flat
    return flat[:limit].rstrip() + "…"


def _consensus_reached(task: Task) -> bool | None:
    if (task.status or "") != "approved":
        return None
    record = task.final_record if isinstance(task.final_record, dict) else None
    if not record:
        return None
    agreement = record.get("inter_annotator_agreement")
    if isinstance(agreement, dict) and "consensus_reached" in agreement:
        return bool(agreement.get("consensus_reached"))
    return None


def serialize_task(task: Task, required_annotators: int | None = None) -> dict[str, Any]:
    """TaskResponse-shaped dict for one relational task row.

    ``required_annotators`` defaults to the owning production queue's value
    (``task.queue`` should be eager-loaded by the caller)."""
    if required_annotators is None:
        owner = task.queue
        required_annotators = int(
            (owner.required_annotators if owner is not None else None) or DEFAULT_REQUIRED_ANNOTATORS
        )
    return {
        "id": str(task.id),
        "queue_id": str(task.queue_id),
        "file_url": task.file_url or "",
        "file_name": task.file_name or "",
        "file_type": task.file_type or "",
        "batch_name": task.batch_name or "",
        "status": task.status or "pending",
        "environment": task.environment or "production",
        "assigned_to": str(task.assigned_to) if task.assigned_to else None,
        "assigned_to_name": task.assigned_to_name or None,
        "submitted_at": task.submitted_at,
        "started_at": task.started_at,
        "paused_at": task.paused_at,
        "timer_seconds": task.timer_seconds or DEFAULT_TIMER_SECONDS,
        "elapsed_seconds": task.elapsed_seconds or 0,
        "declined_reason": task.declined_reason or "",
        "qa_notes": task.qa_notes or "",
        "submitted_by": task.submitted_by or "",
        "annotation_version": task.annotation_version or 1,
        "created_at": task.created_at,
        "updated_at": task.updated_at or task.created_at,
        # SPEC2 additions
        "dataset": task.dataset or "",
        "input_preview": input_preview(task.input_text),
        "sequence": int(task.sequence or 0),
        "submitted_count": int(task.submitted_count or 0),
        "required_annotators": int(required_annotators),
        "finalized_by_name": task.finalized_by_name or None,
        "finalized_at": task.finalized_at,
        "consensus_reached": _consensus_reached(task),
        "qa_queue_id": str(task.qa_queue_id) if task.qa_queue_id else None,
    }


def _serialize_queue(
    queue: Queue,
    project_name: str | None = None,
    counts: dict[str, int] | None = None,
) -> dict[str, Any]:
    """QueueResponse-shaped dict. ``counts`` comes from ``_task_counts``; the
    ``assigned_users`` relationship is expected to be loaded (selectinload in
    list paths, lazy for single fetches)."""
    c = counts or _EMPTY_COUNTS
    is_qa = (queue.annotation_type or "production") == "qa"

    id_to_name = {str(u.id): u.full_name for u in (queue.assigned_users or [])}
    assigned_user_ids = list(id_to_name.keys())
    assigned_user_names = list(id_to_name.values())

    # Primary assignee — the single column, falling back to the first member
    # of the pool when the column is unset but the join table has rows.
    primary_id = (
        str(queue.assigned_user_id)
        if queue.assigned_user_id
        else (assigned_user_ids[0] if assigned_user_ids else None)
    )
    primary_name = id_to_name.get(primary_id) if primary_id else None
    if primary_id and primary_name is None and queue.assigned_user is not None:
        primary_name = queue.assigned_user.full_name

    if is_qa:
        # QA queue: tasks are those routed here (Task.qa_queue_id == id).
        # total = awaiting + approved; submitted = awaiting review.
        total = c.get("qa_total", 0)
        pending = 0
        active = 0
        submitted = c.get("qa_submitted", 0)
        approved = c.get("qa_approved", 0)
        returned = 0
        rejected = declined = skipped = 0
    else:
        total = c.get("total", 0)
        pending = c.get("pending", 0)
        active = c.get("active", 0)
        submitted = c.get("submitted", 0)
        approved = c.get("approved", 0)
        returned = c.get("returned", 0)
        rejected = c.get("rejected", 0)
        declined = c.get("declined", 0)
        skipped = c.get("skipped", 0)

    return {
        "id": str(queue.id),
        "name": queue.name,
        "project_id": str(queue.project_id) if queue.project_id else "",
        "project_name": project_name,
        "task_name": queue.task_name or "",
        "batch_name": queue.batch_name or "",
        "annotation_type": queue.annotation_type or "production",
        "priority": queue.priority or "medium",
        "sla_hours": queue.sla_hours or 24,
        "status": queue.status or "inactive",
        "user_status": None,
        "assigned_user_id": primary_id,
        "assigned_user_name": primary_name,
        "assigned_user_ids": assigned_user_ids,
        "assigned_user_names": assigned_user_names,
        "linked_qa_queue_id": str(queue.linked_qa_queue_id) if queue.linked_qa_queue_id else None,
        "source_production_queue_id": (
            str(queue.source_production_queue_id) if queue.source_production_queue_id else None
        ),
        "total_tasks": total,
        "pending_tasks": pending,
        "active_tasks": active,
        "submitted_tasks": submitted,
        "approved_tasks": approved,
        "rejected_tasks": rejected,
        "declined_tasks": declined,
        "skipped_tasks": skipped,
        "returned_tasks": returned,
        "required_annotators": int(queue.required_annotators or DEFAULT_REQUIRED_ANNOTATORS),
        "user_done_tasks": 0,
        "timer_seconds": queue.timer_seconds or DEFAULT_TIMER_SECONDS,
        "created_at": queue.created_at,
        "updated_at": queue.updated_at or queue.created_at,
    }


def _task_counts(db: Session, queue_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict[str, int]]:
    """Two grouped queries giving the per-queue status counters: production
    counters keyed by ``Task.queue_id`` and QA counters keyed by
    ``Task.qa_queue_id`` (both merged into one dict per queue id)."""
    if not queue_ids:
        return {}

    def bucket(*statuses: str):
        return func.count(case((Task.status.in_(statuses), 1)))

    result: dict[uuid.UUID, dict[str, int]] = {}

    rows = (
        db.query(
            Task.queue_id,
            func.count(Task.id).label("total"),
            bucket(*PENDING_STATUSES).label("pending"),
            bucket("active", "paused").label("active"),
            bucket(*SUBMITTED_STATUSES).label("submitted"),
            bucket("approved").label("approved"),
            bucket("rejected").label("rejected"),
            bucket("declined").label("declined"),
            bucket("skipped").label("skipped"),
            bucket("returned").label("returned"),
        )
        .filter(Task.queue_id.in_(queue_ids))
        .group_by(Task.queue_id)
        .all()
    )
    for row in rows:
        entry = dict(_EMPTY_COUNTS)
        entry.update({
            "total": int(row.total or 0),
            "pending": int(row.pending or 0),
            "active": int(row.active or 0),
            "submitted": int(row.submitted or 0),
            "approved": int(row.approved or 0),
            "rejected": int(row.rejected or 0),
            "declined": int(row.declined or 0),
            "skipped": int(row.skipped or 0),
            "returned": int(row.returned or 0),
        })
        result[row.queue_id] = entry

    qa_rows = (
        db.query(
            Task.qa_queue_id,
            bucket(*QA_AWAITING_STATUSES, *QA_DONE_STATUSES).label("total"),
            bucket(*QA_AWAITING_STATUSES).label("submitted"),
            bucket(*QA_DONE_STATUSES).label("approved"),
        )
        .filter(Task.qa_queue_id.in_(queue_ids))
        .group_by(Task.qa_queue_id)
        .all()
    )
    for row in qa_rows:
        entry = result.setdefault(row.qa_queue_id, dict(_EMPTY_COUNTS))
        entry["qa_total"] = int(row.total or 0)
        entry["qa_submitted"] = int(row.submitted or 0)
        entry["qa_approved"] = int(row.approved or 0)

    return result


def _project_names(db: Session, queues: list[Queue]) -> dict[Any, str]:
    project_ids = {q.project_id for q in queues if q.project_id}
    if not project_ids:
        return {}
    return {
        pid: pname
        for pid, pname in db.query(Project.id, Project.name).filter(Project.id.in_(project_ids))
    }


def _enrich_queue(db: Session, queue: Queue) -> dict[str, Any]:
    """Serialize a single queue with project name + task counters."""
    names = _project_names(db, [queue])
    counts = _task_counts(db, [queue.id])
    return _serialize_queue(queue, names.get(queue.project_id), counts.get(queue.id))


def _load_queue(db: Session, queue_id: str) -> Queue | None:
    queue_uuid = _parse_uuid(queue_id)
    if queue_uuid is None:
        return None
    return (
        db.query(Queue)
        .options(selectinload(Queue.assigned_users))
        .filter(Queue.id == queue_uuid)
        .first()
    )


def _apply_user_view(db: Session, queues: list[Queue], items: list[dict[str, Any]], uid: uuid.UUID) -> None:
    """Fill ``user_done_tasks`` + ``user_status`` for the requesting annotator.

    Production queue: done = tasks with a SUBMITTED annotation by this user;
      status = completed (queue completed, or done == total > 0)
             | in_progress (any draft/submitted annotation by this user)
             | active.
    QA queue: done = approved tasks routed to it; status = completed (queue
      completed) | in_progress (anything approved) | active.
    """
    if not queues:
        return
    prod_ids = [q.id for q in queues if (q.annotation_type or "production") != "qa"]

    done_by_queue: dict[uuid.UUID, int] = {}
    touched: set[uuid.UUID] = set()
    if prod_ids:
        rows = (
            db.query(Task.queue_id, TaskAnnotation.status, func.count(TaskAnnotation.id))
            .join(Task, Task.id == TaskAnnotation.task_id)
            .filter(
                Task.queue_id.in_(prod_ids),
                TaskAnnotation.user_id == uid,
                TaskAnnotation.status.in_(("draft", "submitted")),
            )
            .group_by(Task.queue_id, TaskAnnotation.status)
            .all()
        )
        for qid, astatus, n in rows:
            touched.add(qid)
            if astatus == "submitted":
                done_by_queue[qid] = int(n or 0)

    for queue, item in zip(queues, items):
        if item["annotation_type"] == "qa":
            done = item["approved_tasks"]
            item["user_done_tasks"] = done
            if item["status"] == "completed":
                item["user_status"] = "completed"
            elif done > 0:
                item["user_status"] = "in_progress"
            else:
                item["user_status"] = "active"
            continue

        done = done_by_queue.get(queue.id, 0)
        total = item["total_tasks"]
        item["user_done_tasks"] = done
        if item["status"] == "completed" or (total > 0 and done >= total):
            item["user_status"] = "completed"
        elif queue.id in touched:
            item["user_status"] = "in_progress"
        else:
            item["user_status"] = "active"


# ─── Read ──────────────────────────────────────────────────────────────────

def list_queues(
    db: Session,
    project_id: str | None = None,
    annotation_type: str | None = None,
    status: str | None = None,
    priority: str | None = None,
    assigned_user_id: str | None = None,
    search: str | None = None,
    created_from: str | None = None,
    created_to: str | None = None,
    exclude_completed: bool = False,
    page: int | None = None,
    page_size: int | None = None,
) -> tuple[list[dict[str, Any]], int, int, int]:
    """Return (items, total, page, page_size). When page/page_size are None the
    full filtered set is returned in a single page."""
    query = db.query(Queue).options(selectinload(Queue.assigned_users))

    if project_id:
        pid = _parse_uuid(project_id)
        if pid is not None:
            query = query.filter(Queue.project_id == pid)
    if annotation_type:
        query = query.filter(Queue.annotation_type == annotation_type)
    if status:
        query = query.filter(Queue.status == status)
    if priority:
        query = query.filter(Queue.priority == priority)

    # Created-date range: inclusive calendar dates ("YYYY-MM-DD"). Invalid
    # values are ignored, matching the bad-UUID behaviour above.
    if created_from:
        try:
            query = query.filter(Queue.created_at >= datetime.fromisoformat(created_from))
        except ValueError:
            pass
    if created_to:
        try:
            end = datetime.fromisoformat(created_to) + timedelta(days=1)
            query = query.filter(Queue.created_at < end)
        except ValueError:
            pass

    if exclude_completed:
        query = query.filter(Queue.status != "completed")

    uid: uuid.UUID | None = None
    if assigned_user_id:
        # "My queues" — a user counts as assigned if they're anywhere in the
        # shared pool. EXISTS subquery hits ix_queue_assigned_users_user_id.
        uid = _parse_uuid(assigned_user_id)
        if uid is not None:
            query = query.filter(Queue.assigned_users.any(User.id == uid))

    if search:
        term = f"%{search.strip().lower()}%"
        query = query.filter(
            func.lower(Queue.name).like(term)
            | func.lower(func.coalesce(Queue.task_name, "")).like(term)
            | func.lower(func.coalesce(Queue.batch_name, "")).like(term)
        )

    query = query.order_by(Queue.created_at.desc())
    queues, total, eff_page, eff_size = paginate_query(query, page, page_size)

    names = _project_names(db, queues)
    counts = _task_counts(db, [q.id for q in queues])
    items = [_serialize_queue(q, names.get(q.project_id), counts.get(q.id)) for q in queues]

    if uid is not None and queues:
        _apply_user_view(db, queues, items, uid)

    return items, total, eff_page, eff_size


def get_queue_by_id(db: Session, queue_id: str) -> dict[str, Any] | None:
    queue = _load_queue(db, queue_id)
    if not queue:
        return None
    return _enrich_queue(db, queue)


def get_queue_access_meta(db: Session, queue_id: str) -> dict[str, Any] | None:
    """Minimal queue facts for permission gates: never touches tasks.

    Returns {"id", "name", "annotation_type", "status", "assigned_user_ids",
    "linked_qa_queue_id", "source_production_queue_id", "required_annotators"}
    or None when the queue doesn't exist.
    """
    queue_uuid = _parse_uuid(queue_id)
    if queue_uuid is None:
        return None
    row = (
        db.query(
            Queue.id,
            Queue.name,
            Queue.annotation_type,
            Queue.status,
            Queue.assigned_user_id,
            Queue.linked_qa_queue_id,
            Queue.source_production_queue_id,
            Queue.required_annotators,
        )
        .filter(Queue.id == queue_uuid)
        .first()
    )
    if row is None:
        return None
    assigned_ids = [
        str(r[0])
        for r in db.query(queue_assigned_users.c.user_id).filter(
            queue_assigned_users.c.queue_id == queue_uuid
        )
    ]
    primary = str(row.assigned_user_id) if row.assigned_user_id else None
    if primary and primary not in assigned_ids:
        assigned_ids.append(primary)
    return {
        "id": str(row.id),
        "name": row.name,
        "annotation_type": row.annotation_type or "production",
        "status": row.status or "inactive",
        "assigned_user_ids": assigned_ids,
        "linked_qa_queue_id": str(row.linked_qa_queue_id) if row.linked_qa_queue_id else None,
        "source_production_queue_id": (
            str(row.source_production_queue_id) if row.source_production_queue_id else None
        ),
        "required_annotators": int(row.required_annotators or DEFAULT_REQUIRED_ANNOTATORS),
    }


def list_queue_tasks(
    db: Session,
    queue_id: str,
    page: int | None = None,
    page_size: int | None = None,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], dict[str, int]] | None:
    """Return (queue_dict, summary_dict, task_dicts, pagination) or None when
    the queue doesn't exist. The summary is always computed over ALL tasks;
    only the returned task list is paginated.

    Production queue: tasks where ``Task.queue_id == id``; completed =
    approved, remaining = total − approved, submitted_to_qa = submitted +
    approved. QA queue: tasks where ``Task.qa_queue_id == id``; completed =
    approved, remaining = awaiting (submitted).
    """
    queue = _load_queue(db, queue_id)
    if not queue:
        return None

    queue_dict = _enrich_queue(db, queue)
    is_qa = queue_dict["annotation_type"] == "qa"

    if is_qa:
        total = queue_dict["total_tasks"]
        completed = queue_dict["approved_tasks"]
        remaining = queue_dict["submitted_tasks"]
        submitted_to_qa = total
        task_filter = Task.qa_queue_id == queue.id
    else:
        total = queue_dict["total_tasks"]
        completed = queue_dict["approved_tasks"]
        remaining = max(total - completed, 0)
        submitted_to_qa = queue_dict["submitted_tasks"] + completed
        task_filter = Task.queue_id == queue.id

    progress = round((completed / total) * 100) if total else 0

    summary = {
        "queue_name": queue_dict["name"],
        "queue_type": queue_dict["annotation_type"],
        "total_tasks": total,
        "completed_tasks": completed,
        "pending_tasks": remaining,
        "submitted_to_qa": submitted_to_qa,
        "assigned_user": queue_dict.get("assigned_user_name"),
        "progress_percent": progress,
        "status": queue_dict["status"],
    }

    task_query = (
        db.query(Task)
        .options(joinedload(Task.queue))
        .filter(task_filter)
        .order_by(Task.sequence.asc(), Task.created_at.asc(), Task.id.asc())
    )
    tasks, task_total, eff_page, eff_size = paginate_query(task_query, page, page_size)
    task_dicts = [serialize_task(t) for t in tasks]
    pagination = {"total": task_total, "page": eff_page, "page_size": eff_size}
    return queue_dict, summary, task_dicts, pagination


# ─── Write ─────────────────────────────────────────────────────────────────

def _new_task(
    queue: Queue,
    raw: Any,
    sequence: int,
    batch_name: str,
    timer_seconds: int,
    now: datetime,
) -> Task:
    t = raw if isinstance(raw, dict) else dict(raw)
    meta = t.get("meta_data")
    meta = dict(meta) if isinstance(meta, dict) else {}
    annotation_data = t.get("annotation_data")
    input_text = t.get("input")
    if input_text is None:
        input_text = t.get("input_text")
    input_text = "" if input_text is None else str(input_text)
    dataset = str(t.get("dataset") or "").strip()
    source = str(meta.get("source") or "").strip() or "real_user"

    return Task(
        id=uuid.uuid4(),
        queue_id=queue.id,
        file_url=t.get("file_url") or "",
        file_name=t.get("file_name") or "",
        file_type=t.get("file_type") or "",
        batch_name=t.get("batch_name") or batch_name,
        status="pending",
        environment="production",
        assigned_to=None,
        assigned_to_name=None,
        submitted_at=None,
        started_at=None,
        paused_at=None,
        annotation_data=annotation_data if isinstance(annotation_data, dict) else {},
        draft_data={},
        annotation_version=1,
        annotation_history=[],
        timer_seconds=timer_seconds,
        elapsed_seconds=0,
        declined_reason="",
        qa_notes="",
        submitted_by="",
        created_at=now,
        updated_at=now,
        # SPEC2 columns
        dataset=dataset,
        input_text=input_text,
        sequence=sequence,
        source=source,
        meta_data=meta,
        submitted_count=0,
        final_data=None,
        final_record=None,
        finalized_by=None,
        finalized_by_name=None,
        finalized_at=None,
        qa_queue_id=None,
    )


def create_queue(db: Session, payload: dict[str, Any], created_by: str) -> dict[str, Any]:
    """Create a queue (+ its tasks). A PRODUCTION queue also gets its linked
    QA queue in the same transaction; the production QueueResponse is
    returned."""
    now = _now()
    project_id = _parse_uuid(payload.get("project_id")) if payload.get("project_id") else None
    created_by_uuid = _parse_uuid(created_by)

    short = uuid.uuid4().hex[:8]
    batch_name = (payload.get("batch_name") or f"B-{short}").strip()
    annotation_type = payload.get("annotation_type") or "production"
    timer_seconds = int(payload.get("timer_seconds") or DEFAULT_TIMER_SECONDS)
    priority = payload.get("priority") or "medium"
    sla_hours = int(payload.get("sla_hours") or 24)
    required = int(payload.get("required_annotators") or DEFAULT_REQUIRED_ANNOTATORS)
    required = min(5, max(1, required))
    name = payload["name"].strip()

    queue = Queue(
        id=uuid.uuid4(),
        name=name,
        project_id=project_id,
        task_name=(payload.get("task_name") or "").strip(),
        batch_name=batch_name,
        annotation_type=annotation_type,
        priority=priority,
        sla_hours=sla_hours,
        status="inactive",
        assigned_user_id=None,
        linked_qa_queue_id=None,
        source_production_queue_id=None,
        timer_seconds=timer_seconds,
        required_annotators=required if annotation_type == "production" else 1,
        created_by=created_by_uuid,
        created_at=now,
        updated_at=now,
    )
    db.add(queue)

    if annotation_type == "production":
        qa_queue = Queue(
            id=uuid.uuid4(),
            name=f"{name} - QA",
            project_id=project_id,
            task_name=(payload.get("task_name") or "").strip(),
            batch_name=batch_name,
            annotation_type="qa",
            priority=priority,
            sla_hours=sla_hours,
            status="inactive",
            assigned_user_id=None,
            linked_qa_queue_id=None,
            source_production_queue_id=queue.id,
            timer_seconds=timer_seconds,
            required_annotators=1,
            created_by=created_by_uuid,
            created_at=now,
            updated_at=now,
        )
        db.add(qa_queue)
        queue.linked_qa_queue_id = qa_queue.id

    for index, raw in enumerate((payload.get("tasks") or [])[:MAX_TASKS_PER_QUEUE], start=1):
        db.add(_new_task(queue, raw, index, batch_name, timer_seconds, now))

    db.commit()
    db.refresh(queue)
    return _enrich_queue(db, queue)


def update_queue(db: Session, queue_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    queue = _load_queue(db, queue_id)
    if not queue:
        return None

    queue.name = payload["name"].strip()
    queue.annotation_type = payload.get("annotation_type") or "production"
    queue.priority = payload.get("priority") or "medium"
    queue.sla_hours = int(payload.get("sla_hours") or 24)
    queue.status = payload.get("status") or "inactive"
    if payload.get("required_annotators"):
        queue.required_annotators = min(5, max(1, int(payload["required_annotators"])))
    queue.updated_at = _now()

    db.commit()
    db.refresh(queue)
    return _enrich_queue(db, queue)


def assign_queue(db: Session, queue_id: str, user_id: str) -> dict[str, Any] | None:
    """Legacy single-user assign: the pool becomes exactly this user."""
    queue = _load_queue(db, queue_id)
    if not queue:
        return None
    user_uuid = _parse_uuid(user_id)
    if user_uuid is None:
        return None
    user = db.query(User).filter(User.id == user_uuid).first()
    if not user:
        return None

    queue.assigned_users = [user]
    queue.assigned_user_id = user_uuid
    queue.status = "active"
    queue.updated_at = _now()

    db.commit()
    db.refresh(queue)
    return _enrich_queue(db, queue)


def set_queue_assignees(db: Session, queue_id: str, user_ids: list[str]) -> dict[str, Any] | None:
    """Replace the full assignee set (set semantics). The primary
    ``assigned_user_id`` is preserved when it survives the edit, otherwise it
    falls back to the first member (or None when the pool is emptied)."""
    queue = _load_queue(db, queue_id)
    if not queue:
        return None

    seen: set[uuid.UUID] = set()
    ordered_uuids: list[uuid.UUID] = []
    for raw in user_ids or []:
        u = _parse_uuid(raw)
        if u is not None and u not in seen:
            seen.add(u)
            ordered_uuids.append(u)

    ordered_users: list[User] = []
    if ordered_uuids:
        by_id = {u.id: u for u in db.query(User).filter(User.id.in_(ordered_uuids)).all()}
        ordered_users = [by_id[u] for u in ordered_uuids if u in by_id]

    queue.assigned_users = ordered_users

    surviving_ids = {u.id for u in ordered_users}
    if queue.assigned_user_id in surviving_ids:
        pass  # primary unchanged
    elif ordered_users:
        queue.assigned_user_id = ordered_users[0].id
    else:
        queue.assigned_user_id = None

    queue.status = "active" if ordered_users else "inactive"
    queue.updated_at = _now()

    db.commit()
    db.refresh(queue)
    return _enrich_queue(db, queue)


def unassign_queue(db: Session, queue_id: str) -> dict[str, Any] | None:
    queue = _load_queue(db, queue_id)
    if not queue:
        return None

    queue.assigned_users = []
    queue.assigned_user_id = None
    queue.status = "inactive"
    queue.updated_at = _now()

    db.commit()
    db.refresh(queue)
    return _enrich_queue(db, queue)


def _detach_qa_queue(db: Session, qa_queue: Queue) -> None:
    """Prepare a QA queue for deletion: its production partner forgets it and
    every task routed to it goes back to "not in QA" (qa_queue_id NULL)."""
    db.query(Queue).filter(Queue.linked_qa_queue_id == qa_queue.id).update(
        {"linked_qa_queue_id": None}, synchronize_session=False
    )
    db.query(Task).filter(Task.qa_queue_id == qa_queue.id).update(
        {"qa_queue_id": None}, synchronize_session=False
    )


def delete_queue(db: Session, queue_id: str) -> bool:
    """Delete a queue. A production queue takes its linked QA queue(s) with
    it (their tasks are the production queue's rows, which cascade); a QA
    queue only clears the production link and NULLs ``tasks.qa_queue_id``."""
    queue_uuid = _parse_uuid(queue_id)
    if queue_uuid is None:
        return False
    queue = db.query(Queue).filter(Queue.id == queue_uuid).first()
    if not queue:
        return False

    if (queue.annotation_type or "production") == "qa":
        _detach_qa_queue(db, queue)
        db.query(Queue).filter(Queue.source_production_queue_id == queue_uuid).update(
            {"source_production_queue_id": None}, synchronize_session=False
        )
        db.delete(queue)
        db.commit()
        return True

    # Production: collect every QA queue pointing at (or pointed to by) it.
    partner_ids: set[uuid.UUID] = set()
    if queue.linked_qa_queue_id:
        partner_ids.add(queue.linked_qa_queue_id)
    for (qid,) in db.query(Queue.id).filter(Queue.source_production_queue_id == queue_uuid):
        partner_ids.add(qid)
    partner_ids.discard(queue_uuid)

    partners = (
        db.query(Queue).filter(Queue.id.in_(partner_ids), Queue.annotation_type == "qa").all()
        if partner_ids
        else []
    )
    queue.linked_qa_queue_id = None
    db.flush()
    for partner in partners:
        _detach_qa_queue(db, partner)
        db.delete(partner)

    # Any other queue still referencing this one must let go before DELETE.
    db.query(Queue).filter(Queue.linked_qa_queue_id == queue_uuid).update(
        {"linked_qa_queue_id": None}, synchronize_session=False
    )
    db.query(Queue).filter(Queue.source_production_queue_id == queue_uuid).update(
        {"source_production_queue_id": None}, synchronize_session=False
    )

    # Bulk-delete the task rows (annotations cascade at the DB level) so a
    # 5000-prompt queue doesn't turn into 5000 ORM deletes.
    db.query(Task).filter(Task.queue_id == queue_uuid).delete(synchronize_session=False)
    db.delete(queue)
    db.commit()
    return True
