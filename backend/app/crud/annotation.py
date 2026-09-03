"""Annotation-workspace CRUD (SPEC2 section 5.3).

Every annotator assigned to a production queue annotates EVERY task; one
``TaskAnnotation`` row per (task, user). When ``required_annotators``
submissions exist the task moves to the linked QA queue, where a reviewer
finalises (``approved``) or returns it (``returned``).

All functions take an open ``Session`` and commit themselves when they write.
Serialisers return plain dicts shaped exactly like the SPEC2 payloads.
"""

from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from app.core.taxonomy import length_bucket
from app.crud.queue import get_queue_by_id
from app.models.queue import Queue
from app.models.task import Task
from app.models import TaskAnnotation, TaskOutput
from app.services.consensus import (

    build_record,
    compute_consensus,
    normalise_annotation,
    validate_annotation,
)

PREVIEW_CHARS = 140

# Task statuses in which an annotator can no longer touch their annotation.
LOCKED_TASK_STATUSES = ("submitted", "approved")


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


def _preview(text: str | None, limit: int = PREVIEW_CHARS) -> str:
    """First ``limit`` characters of the prompt collapsed onto one line."""
    if not text:
        return ""
    single = " ".join(str(text).split())
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
    return ann is None or ann.status in ("draft", "returned")


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


def get_my_annotation(task: Task, user_id: str) -> TaskAnnotation | None:
    uid = _parse_uuid(user_id)
    for ann in task.annotations or []:
        if ann.user_id == uid:
            return ann
    return None


def required_annotators_for(queue: Queue | None) -> int:
    if queue is None:
        return 1
    return int(getattr(queue, "required_annotators", None) or 1)


# ─── Serialisers ───────────────────────────────────────────────────────────

def serialize_task_block(task: Task, queue: Queue | None = None) -> dict[str, Any]:
    """The ``task`` block shared by the production and QA workspace payloads."""
    queue = queue or task.queue
    text = task.input_text or ""
    return {
        "id": str(task.id),
        "queue_id": str(task.queue_id),
        "queue_name": (queue.name if queue else None) or "",
        "sequence": int(task.sequence or 0),
        "dataset": task.dataset or "",
        "input_text": text,
        "data_length_chars": len(text),
        "data_length_bucket": length_bucket(len(text)),
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
        "editable": is_editable(task, mine),
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
    "full" when every customer key is full, "none" when any is none,
    otherwise "majority". None when there is nothing to compare."""
    if not agreement:
        return None
    levels = [v for k, v in agreement.items() if k != "consensus_reached"]
    if not levels:
        return None
    if any(v == "none" for v in levels):
        return "none"
    if all(v == "full" for v in levels):
        return "full"
    return "majority"


def qa_draft_of(task: Task) -> dict[str, Any] | None:
    """The reviewer's saved-but-not-finalised QA form (``tasks.draft_data``),
    or None. Lets a reviewer stop and resume exactly like a production
    annotator."""
    d = task.draft_data if isinstance(task.draft_data, dict) else None
    if not d or not isinstance(d.get("data"), dict):
        return None
    return {
        "data": d.get("data") or {},
        "qa_notes": str(d.get("qa_notes") or ""),
        "elapsed_seconds": int(d.get("elapsed_seconds") or 0),
        "user_id": str(d.get("user_id") or ""),
        "user_name": str(d.get("user_name") or ""),
        "updated_at": d.get("updated_at"),
    }


def qa_task_payload(task: Task) -> dict[str, Any]:
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
        "qa_draft": qa_draft_of(task),
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


# ─── Production workspace ──────────────────────────────────────────────────

def list_workspace_tasks(db: Session, queue: Queue, user_id: str) -> dict[str, Any]:
    """Payload of GET /workspace/queues/{id} for one annotator."""
    uid = _parse_uuid(user_id)
    tasks = (
        db.query(Task)
        .filter(Task.queue_id == queue.id)
        .order_by(Task.sequence.asc(), Task.created_at.asc(), Task.id.asc())
        .all()
    )
    mine_by_task: dict[uuid.UUID, TaskAnnotation] = {}
    if tasks and uid is not None:
        rows = (
            db.query(TaskAnnotation)
            .filter(
                TaskAnnotation.task_id.in_([t.id for t in tasks]),
                TaskAnnotation.user_id == uid,
            )
            .all()
        )
        mine_by_task = {a.task_id: a for a in rows}

    required = required_annotators_for(queue)
    items: list[dict[str, Any]] = []
    my_done = 0
    for t in tasks:
        mine = mine_by_task.get(t.id)
        status = my_status_for(mine)
        if status == "submitted":
            my_done += 1
        items.append({
            "id": str(t.id),
            "sequence": int(t.sequence or 0),
            "dataset": t.dataset or "",
            "preview": _preview(t.input_text),
            "status": t.status or "pending",
            "submitted_count": int(t.submitted_count or 0),
            "required_annotators": required,
            "my_status": status,
        })

    queue_dict = get_queue_by_id(db, str(queue.id)) or {}
    return {"queue": queue_dict, "tasks": items, "my_done": my_done}


def next_task_id(db: Session, queue_id: uuid.UUID, user_id: str, after_sequence: int) -> str | None:
    """A random task the user can still work on (shuffled pool).

    The pool excludes locked tasks (submitted/approved: enough annotators
    already submitted, so a further annotator must never receive them), tasks
    this user already submitted or declined, and the task just left
    (``after_sequence``) unless it is the only one left. A task the user has
    paused as a draft is preferred so they resume their own work first.
    None when nothing is left.
    """
    uid = _parse_uuid(user_id)
    tasks = (
        db.query(Task.id, Task.sequence, Task.status)
        .filter(Task.queue_id == queue_id, Task.status.notin_(LOCKED_TASK_STATUSES))
        .all()
    )
    if not tasks:
        return None
    done_ids: set[uuid.UUID] = set()
    draft_ids: set[uuid.UUID] = set()
    if uid is not None:
        rows = db.query(TaskAnnotation.task_id, TaskAnnotation.status).filter(
            TaskAnnotation.task_id.in_([t.id for t in tasks]),
            TaskAnnotation.user_id == uid,
        )
        for task_id, astatus in rows:
            if astatus in ("submitted", "declined"):
                done_ids.add(task_id)
            elif astatus == "draft":
                draft_ids.add(task_id)
    candidates = [t for t in tasks if t.id not in done_ids]
    if not candidates:
        return None
    others = [t for t in candidates if (t.sequence or 0) != after_sequence]
    pool = others or candidates
    resumable = [t for t in pool if t.id in draft_ids]
    chosen = random.choice(resumable or pool)
    return str(chosen.id)


def upsert_draft(
    db: Session,
    task: Task,
    user: dict[str, Any],
    data: dict[str, Any],
    elapsed_seconds: int,
) -> TaskAnnotation:
    """Create or update the caller's draft; task goes ``active`` if it was
    pending/returned. Caller must have checked ``is_editable`` first."""
    now = _now()
    uid = _parse_uuid(user["id"])
    ann = get_my_annotation(task, user["id"])
    if ann is None:
        ann = TaskAnnotation(
            id=uuid.uuid4(),
            task_id=task.id,
            user_id=uid,
            user_name=user.get("full_name") or "",
            status="draft",
            data=data if isinstance(data, dict) else {},
            elapsed_seconds=max(0, int(elapsed_seconds or 0)),
            submitted_at=None,
            created_at=now,
            updated_at=now,
        )
        db.add(ann)
        task.annotations.append(ann)
    else:
        ann.status = "draft"  # returned -> draft as well
        ann.user_name = user.get("full_name") or ann.user_name
        ann.data = data if isinstance(data, dict) else {}
        ann.elapsed_seconds = max(0, int(elapsed_seconds or 0))
        ann.updated_at = now

    if task.status in ("pending", "returned"):
        task.status = "active"
    if task.started_at is None:
        task.started_at = now
    task.updated_at = now

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
    ann = get_my_annotation(task, user["id"])
    if ann is None:
        ann = TaskAnnotation(
            id=uuid.uuid4(),
            task_id=task.id,
            user_id=uid,
            user_name=user.get("full_name") or "",
            status="declined",
            data={"declined": True, "reason": reason},
            created_at=now,
            updated_at=now,
        )
        db.add(ann)
        task.annotations.append(ann)
    else:
        ann.status = "declined"
        ann.user_name = user.get("full_name") or ann.user_name
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
    ann = get_my_annotation(task, user["id"])
    if ann is not None and ann.status == "draft":
        db.delete(ann)
        remaining = [a for a in (task.annotations or []) if a is not ann]
        if not remaining and task.status == "active":
            task.status = "pending"
            task.started_at = None
    task.updated_at = now
    db.commit()
    db.refresh(task)



def ensure_qa_queue(db: Session, prod: Queue, created_by: uuid.UUID | None = None) -> Queue:
    """Return the production queue's linked QA queue, creating it lazily when
    it is missing (e.g. queues created before the QA link existed). Does NOT
    commit; the caller's transaction covers it."""
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
    """Validate + submit the caller's annotation. Returns the validation error
    list (empty on success). On success the task's submitted_count is
    refreshed and it moves to the QA queue once enough submissions exist."""
    errors = validate_annotation(data)
    if errors:
        return errors
    clean = normalise_annotation(data)

    now = _now()
    uid = _parse_uuid(user["id"])
    ann = get_my_annotation(task, user["id"])
    if ann is None:
        ann = TaskAnnotation(
            id=uuid.uuid4(),
            task_id=task.id,
            user_id=uid,
            user_name=user.get("full_name") or "",
            status="submitted",
            data=clean,
            elapsed_seconds=max(0, int(elapsed_seconds or 0)),
            submitted_at=now,
            created_at=now,
            updated_at=now,
        )
        db.add(ann)
        task.annotations.append(ann)
    else:
        ann.status = "submitted"
        ann.user_name = user.get("full_name") or ann.user_name
        ann.data = clean
        ann.elapsed_seconds = max(0, int(elapsed_seconds or 0))
        ann.submitted_at = now
        ann.updated_at = now
    db.flush()

    # Record in tasks_output table
    derived = _derive_output(clean)
    sev = clean.get("severity") if isinstance(clean.get("severity"), dict) else {}
    out_row = (
        db.query(TaskOutput)
        .filter(TaskOutput.task_id == task.id, TaskOutput.user_id == uid)
        .first()
    )
    if out_row is None:
        out_row = TaskOutput(
            id=uuid.uuid4(),
            task_id=task.id,
            user_id=uid,
            user_name=user.get("full_name") or "",
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
        out_row.user_name = user.get("full_name") or out_row.user_name
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
        db.query(func.count(TaskAnnotation.id))
        .filter(TaskAnnotation.task_id == task.id, TaskAnnotation.status == "submitted")
        .scalar()
        or 0
    )
    task.submitted_count = submitted

    prod = task.queue or get_queue(db, str(task.queue_id))
    required = required_annotators_for(prod)
    if submitted >= required:
        task.status = "submitted"
        task.submitted_at = now
        if prod is not None:
            qa = ensure_qa_queue(db, prod, created_by=uid)
            task.qa_queue_id = qa.id
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
    the calling reviewer stopped on (so the workspace resumes it first)."""
    uid = str(user_id or "")
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
            "my_draft": bool(
                uid and t.status == "submitted" and isinstance(t.draft_data, dict)
                and str(t.draft_data.get("user_id") or "") == uid
            ),
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


def next_qa_task_id(
    db: Session, qa_queue_id: uuid.UUID | None, after_sequence: int, user_id: str | None = None
) -> str | None:
    """A random task still awaiting review in the QA queue (shuffled pool),
    excluding the task just left unless it is the only one. A task the caller
    paused (their QA draft) is preferred so they resume their own work."""
    if qa_queue_id is None:
        return None
    rows = (
        db.query(Task.id, Task.sequence, Task.draft_data)
        .filter(Task.qa_queue_id == qa_queue_id, Task.status == "submitted")
        .all()
    )
    if not rows:
        return None
    others = [r for r in rows if (r.sequence or 0) != after_sequence]
    pool = others or rows
    uid = str(user_id or "")
    mine = [
        r for r in pool
        if uid and isinstance(r.draft_data, dict) and str(r.draft_data.get("user_id") or "") == uid
    ]
    chosen = random.choice(mine or pool)
    return str(chosen.id)


def save_qa_draft(
    db: Session,
    task: Task,
    user: dict[str, Any],
    data: dict[str, Any],
    qa_notes: str,
    elapsed_seconds: int,
) -> None:
    """Store the reviewer's in-progress final form (Save / Stop and resume)."""
    now = _now()
    task.draft_data = {
        "data": data if isinstance(data, dict) else {},
        "qa_notes": qa_notes or "",
        "elapsed_seconds": max(0, int(elapsed_seconds or 0)),
        "user_id": str(user["id"]),
        "user_name": user.get("full_name") or "",
        "updated_at": now.isoformat(),
    }
    task.updated_at = now
    db.commit()
    db.refresh(task)


def release_qa_task(db: Session, task: Task) -> None:
    """Discard the reviewer's QA draft; the task stays awaiting review."""
    task.draft_data = {}
    task.updated_at = _now()
    db.commit()
    db.refresh(task)


def preview_record(task: Task, data: dict[str, Any]) -> dict[str, Any]:
    annotations = submitted_annotations(task)
    return build_record(task, annotations, normalise_annotation(data))


def _maybe_complete_queues(db: Session, task: Task, now: datetime) -> None:
    """When every task of the source production queue is approved, mark both
    the production queue and its QA queue completed."""
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
    Returns validation errors (empty on success)."""
    errors = validate_annotation(data)
    if errors:
        return errors
    clean = normalise_annotation(data)
    annotations = submitted_annotations(task)

    now = _now()
    task.final_data = clean
    task.final_record = build_record(task, annotations, clean)
    task.status = "approved"
    task.finalized_by = _parse_uuid(user["id"])
    task.finalized_by_name = user.get("full_name") or ""
    task.finalized_at = now
    task.qa_notes = qa_notes or ""
    task.draft_data = {}
    task.submitted_by = user.get("full_name") or ""
    task.updated_at = now
    _maybe_complete_queues(db, task, now)

    db.commit()
    db.refresh(task)
    return []


def return_task(db: Session, task: Task, qa_notes: str) -> None:
    """Send a task back to the annotators: status returned, detached from the
    QA queue, every annotation flagged ``returned`` (data kept)."""
    now = _now()
    task.status = "returned"
    task.qa_queue_id = None
    task.submitted_count = 0
    task.qa_notes = qa_notes or ""
    task.draft_data = {}
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
