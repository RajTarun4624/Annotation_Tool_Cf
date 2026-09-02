"""Annotation workspace + QA workspace endpoints (SPEC2 section 5.3).

Access rules
- production endpoints: caller holds the "queues" permission OR is assigned
  to the task's production queue;
- QA endpoints: caller holds "queues" OR is assigned to the QA queue.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.crud import annotation as crud
from app.crud.audit_log import create_audit_log
from app.crud.queue import get_queue_access_meta
from app.models.queue import Queue
from app.models.task import Task
from app.schemas.queue import QueueResponse

router = APIRouter()


# ─── Request bodies ────────────────────────────────────────────────────────

class DraftRequest(BaseModel):
    data: dict[str, Any] = Field(default_factory=dict)
    elapsed_seconds: int = Field(default=0, ge=0)


class SubmitRequest(DraftRequest):
    pass


class DeclineRequest(BaseModel):
    reason: str = ""



class PreviewRequest(BaseModel):
    data: dict[str, Any] = Field(default_factory=dict)


class FinalizeRequest(BaseModel):
    data: dict[str, Any] = Field(default_factory=dict)
    qa_notes: str = ""


class ReturnRequest(BaseModel):
    qa_notes: str = Field(min_length=3)


# ─── Access helpers ────────────────────────────────────────────────────────

def _has_queues_permission(current_user: dict) -> bool:
    return "queues" in set(current_user.get("permissions", []))


def _assigned_or_admin(queue_meta: dict | None, user: dict) -> bool:
    if _has_queues_permission(user):
        return True
    if not queue_meta:
        return False
    return str(user["id"]) in queue_meta.get("assigned_user_ids", [])


def _forbid() -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")


def _load_task_or_404(db: Session, task_id: str) -> Task:
    task = crud.get_task(db, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return task


def _require_production_task_access(db: Session, task: Task, user: dict) -> None:
    if _has_queues_permission(user):
        return
    meta = get_queue_access_meta(db, str(task.queue_id))
    if not _assigned_or_admin(meta, user):
        raise _forbid()


def _require_qa_task_access(db: Session, task: Task, user: dict) -> None:
    if _has_queues_permission(user):
        return
    qa_id = task.qa_queue_id or (task.queue.linked_qa_queue_id if task.queue else None)
    meta = get_queue_access_meta(db, str(qa_id)) if qa_id else None
    if not _assigned_or_admin(meta, user):
        raise _forbid()


def _queue_response(queue_dict: dict[str, Any]) -> dict[str, Any]:
    if not queue_dict:
        return {}
    return QueueResponse.model_validate(queue_dict).model_dump()


def _validation_error(errors: list[str]) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"detail": "Annotation has validation errors.", "errors": errors},
    )


# ─── Production workspace ──────────────────────────────────────────────────

@router.get("/queues/{queue_id}")
def read_workspace_queue(
    queue_id: str,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    meta = get_queue_access_meta(db, queue_id)
    if not meta:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Queue not found")
    if not _assigned_or_admin(meta, current_user):
        raise _forbid()
    if meta.get("annotation_type") == "qa":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Use the QA workspace")
    queue: Queue | None = crud.get_queue(db, queue_id)
    if queue is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Queue not found")
    payload = crud.list_workspace_tasks(db, queue, str(current_user["id"]))
    payload["queue"] = _queue_response(payload["queue"])
    return payload


@router.get("/tasks/{task_id}")
def read_workspace_task(
    task_id: str,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    task = _load_task_or_404(db, task_id)
    _require_production_task_access(db, task, current_user)
    return crud.task_payload(task, str(current_user["id"]))


@router.put("/tasks/{task_id}/draft")
def save_draft(
    task_id: str,
    payload: DraftRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    task = _load_task_or_404(db, task_id)
    _require_production_task_access(db, task, current_user)
    mine = crud.get_my_annotation(task, str(current_user["id"]))
    if not crud.is_editable(task, mine):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This task is no longer editable.",
        )
    crud.upsert_draft(db, task, current_user, payload.data, payload.elapsed_seconds)
    task = _load_task_or_404(db, task_id)
    return crud.task_payload(task, str(current_user["id"]))


@router.post("/tasks/{task_id}/submit")
def submit_task(
    task_id: str,
    payload: SubmitRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    task = _load_task_or_404(db, task_id)
    _require_production_task_access(db, task, current_user)
    mine = crud.get_my_annotation(task, str(current_user["id"]))
    if not crud.is_editable(task, mine):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This task is no longer editable.",
        )
    errors = crud.submit_annotation(db, task, current_user, payload.data, payload.elapsed_seconds)
    if errors:
        return _validation_error(errors)
    task = _load_task_or_404(db, task_id)
    result = crud.task_payload(task, str(current_user["id"]))
    result["next_task_id"] = crud.next_task_id(
        db, task.queue_id, str(current_user["id"]), int(task.sequence or 0)
    )
    return result


@router.post("/tasks/{task_id}/decline")
def decline_workspace_task(
    task_id: str,
    payload: DeclineRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    task = _load_task_or_404(db, task_id)
    _require_production_task_access(db, task, current_user)
    crud.decline_task(db, task, current_user, payload.reason)
    return {
        "success": True,
        "next_task_id": crud.next_task_id(
            db, task.queue_id, str(current_user["id"]), int(task.sequence or 0)
        ),
    }


@router.post("/tasks/{task_id}/release")
def release_workspace_task(
    task_id: str,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    task = _load_task_or_404(db, task_id)
    _require_production_task_access(db, task, current_user)
    crud.release_task(db, task, current_user)
    return {
        "success": True,
        "next_task_id": crud.next_task_id(
            db, task.queue_id, str(current_user["id"]), int(task.sequence or 0)
        ),
    }


@router.post("/tasks/{task_id}/skip")
def skip_workspace_task(
    task_id: str,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    task = _load_task_or_404(db, task_id)
    _require_production_task_access(db, task, current_user)
    return {
        "success": True,
        "next_task_id": crud.next_task_id(
            db, task.queue_id, str(current_user["id"]), int(task.sequence or 0)
        ),
    }



# ─── QA workspace ──────────────────────────────────────────────────────────
# NOTE: "/qa/tasks/..." routes have more path segments than "/qa/{qa_queue_id}"
# so they never collide; the literal paths are still declared first.

@router.get("/qa/tasks/{task_id}")
def read_qa_task(
    task_id: str,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    task = _load_task_or_404(db, task_id)
    _require_qa_task_access(db, task, current_user)
    return crud.qa_task_payload(task)


@router.post("/qa/tasks/{task_id}/preview")
def preview_qa_task(
    task_id: str,
    payload: PreviewRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    task = _load_task_or_404(db, task_id)
    _require_qa_task_access(db, task, current_user)
    return {"record": crud.preview_record(task, payload.data)}


@router.post("/qa/tasks/{task_id}/finalize")
def finalize_qa_task(
    task_id: str,
    payload: FinalizeRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    task = _load_task_or_404(db, task_id)
    _require_qa_task_access(db, task, current_user)
    if task.status != "submitted":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only tasks awaiting review can be finalised.",
        )
    errors = crud.finalize_task(db, task, current_user, payload.data, payload.qa_notes)
    if errors:
        return _validation_error(errors)
    create_audit_log(
        db,
        action="task_finalized",
        resource_type="task",
        resource_id=str(task.id),
        user_id=str(current_user["id"]),
        details={
            "dataset": task.dataset or "",
            "queue_id": str(task.queue_id),
            "qa_queue_id": str(task.qa_queue_id) if task.qa_queue_id else None,
        },
    )
    task = _load_task_or_404(db, task_id)
    result = crud.qa_task_payload(task)
    result["next_task_id"] = crud.next_qa_task_id(db, task.qa_queue_id, int(task.sequence or 0))
    return result


@router.post("/qa/tasks/{task_id}/return")
def return_qa_task(
    task_id: str,
    payload: ReturnRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    task = _load_task_or_404(db, task_id)
    _require_qa_task_access(db, task, current_user)
    if task.status != "submitted":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only tasks awaiting review can be returned.",
        )
    qa_queue_id = task.qa_queue_id
    sequence = int(task.sequence or 0)
    crud.return_task(db, task, payload.qa_notes.strip())
    create_audit_log(
        db,
        action="task_returned",
        resource_type="task",
        resource_id=str(task.id),
        user_id=str(current_user["id"]),
        details={
            "dataset": task.dataset or "",
            "queue_id": str(task.queue_id),
            "qa_notes": payload.qa_notes.strip(),
        },
    )
    return {
        "success": True,
        "next_task_id": crud.next_qa_task_id(db, qa_queue_id, sequence),
    }


@router.get("/qa/{qa_queue_id}")
def read_qa_queue(
    qa_queue_id: str,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    meta = get_queue_access_meta(db, qa_queue_id)
    if not meta:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Queue not found")
    if not _assigned_or_admin(meta, current_user):
        raise _forbid()
    if meta.get("annotation_type") != "qa":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Not a QA queue")
    queue = crud.get_queue(db, qa_queue_id)
    if queue is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Queue not found")
    payload = crud.list_qa_tasks(db, queue)
    payload["queue"] = _queue_response(payload["queue"])
    return payload
