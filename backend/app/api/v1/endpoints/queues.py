from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_permission
from app.crud.audit_log import create_audit_log
from app.crud.queue import (
    assign_queue,
    create_queue,
    delete_queue,
    get_queue_access_meta,
    get_queue_by_id,
    list_queue_tasks,
    list_queues,
    set_queue_assignees,
    unassign_queue,
    update_queue,
)
from app.schemas.pagination import Page
from app.schemas.queue import (
    QueueAssigneesRequest,
    QueueAssignRequest,
    QueueCreateRequest,
    QueueResponse,
    QueueTasksResponse,
    QueueTasksSummary,
    QueueUpdateRequest,
    TaskResponse,
)
from app.services.export import EXPORT_SCOPES, export_queue, resolve_production_queue
from app.services.sheet_import import MAX_SHEET_BYTES, parse_sheet

router = APIRouter()

_EXPORT_FORMATS = ("jsonl", "json", "xlsx")


def _has_queues_permission(current_user: dict) -> bool:
    return "queues" in set(current_user.get("permissions", []))


def _require_queue_access(db: Session, queue_id: str, current_user: dict) -> dict:
    """Access rule shared by the read endpoints: the caller must hold the
    "queues" permission OR be one of the queue's assignees. Returns the cheap
    access-meta dict; raises 404 / 403 otherwise."""
    meta = get_queue_access_meta(db, queue_id)
    if not meta:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Queue not found")
    if _has_queues_permission(current_user):
        return meta
    if str(current_user["id"]) not in meta.get("assigned_user_ids", []):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
    return meta


# ─── Collection routes (literal paths first) ───────────────────────────────

@router.get("/", response_model=Page[QueueResponse])
def read_queues(
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    project_id: str | None = Query(default=None),
    annotation_type: str | None = Query(default=None),
    status: str | None = Query(default=None),
    priority: str | None = Query(default=None),
    assigned_user_id: str | None = Query(default=None),
    search: str | None = Query(default=None),
    created_from: str | None = Query(default=None),
    created_to: str | None = Query(default=None),
    exclude_completed: bool = Query(default=False),
    hide_exhausted: bool = Query(default=False),
    page: int | None = Query(default=None, ge=1),
    page_size: int | None = Query(default=None, ge=1, le=500),
) -> Page[QueueResponse]:
    # Without the "queues" permission a caller only ever sees their own queues.
    if not _has_queues_permission(current_user):
        assigned_user_id = str(current_user["id"])
    items, total, eff_page, eff_size = list_queues(
        db,
        project_id=project_id,
        annotation_type=annotation_type,
        status=status,
        priority=priority,
        assigned_user_id=assigned_user_id,
        search=search,
        created_from=created_from,
        created_to=created_to,
        exclude_completed=exclude_completed,
        page=page,
        page_size=page_size,
        hide_exhausted=hide_exhausted,
    )
    return Page[QueueResponse](
        items=[QueueResponse.model_validate(q) for q in items],
        total=total,
        page=eff_page,
        page_size=eff_size,
    )


@router.post("/", response_model=QueueResponse, status_code=status.HTTP_201_CREATED)
def add_queue(
    payload: QueueCreateRequest,
    current_user: Annotated[dict, Depends(require_permission("queues"))],
    db: Annotated[Session, Depends(get_db)],
) -> QueueResponse:
    created = create_queue(db, payload.model_dump(), str(current_user["id"]))
    create_audit_log(
        db,
        action="queue_created",
        resource_type="queue",
        resource_id=created["id"],
        user_id=str(current_user["id"]),
        details={
            "queue_name": created["name"],
            "annotation_type": created["annotation_type"],
            "task_count": created.get("total_tasks", 0),
            "required_annotators": created.get("required_annotators", 3),
            "linked_qa_queue_id": created.get("linked_qa_queue_id"),
        },
    )
    return QueueResponse.model_validate(created)


@router.post("/parse-sheet")
async def parse_queue_sheet(
    _: Annotated[dict, Depends(require_permission("queues"))],
    file: UploadFile = File(...),
    name_prefix: str | None = Form(default=None),
) -> dict:
    """Turn an uploaded .xlsx/.csv of prompts into the task rows the Create
    Queue modal previews and then posts back as ``tasks``. Nothing is
    persisted here."""
    if not file.filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No file provided")
    content = await file.read()
    if len(content) > MAX_SHEET_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The spreadsheet is larger than 20 MB.",
        )
    return parse_sheet(content, file.filename, name_prefix)


# ─── Exports (before the generic /{queue_id} routes) ───────────────────────

def _export(db: Session, queue_id: str, fmt: str, scope: str, current_user: dict) -> Response:
    _require_queue_access(db, queue_id, current_user)
    queue = resolve_production_queue(db, queue_id)
    if queue is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Production queue not found for this export.",
        )
    scope = (scope or "final").lower()
    if scope not in EXPORT_SCOPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="scope must be one of: final, all",
        )
    body, media_type, filename = export_queue(db, queue, fmt, scope)
    return Response(
        content=body,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{queue_id}/export/jsonl")
def export_queue_jsonl(
    queue_id: str,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    scope: str = Query(default="final"),
) -> Response:
    return _export(db, queue_id, "jsonl", scope, current_user)


@router.get("/{queue_id}/export/json")
def export_queue_json(
    queue_id: str,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    scope: str = Query(default="final"),
) -> Response:
    return _export(db, queue_id, "json", scope, current_user)


@router.get("/{queue_id}/export/xlsx")
def export_queue_xlsx(
    queue_id: str,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    scope: str = Query(default="final"),
) -> Response:
    return _export(db, queue_id, "xlsx", scope, current_user)


# ─── Single-queue routes ───────────────────────────────────────────────────

@router.get("/{queue_id}", response_model=QueueResponse)
def read_queue(
    queue_id: str,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> QueueResponse:
    _require_queue_access(db, queue_id, current_user)
    queue = get_queue_by_id(db, queue_id)
    if not queue:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Queue not found")
    return QueueResponse.model_validate(queue)


@router.get("/{queue_id}/tasks", response_model=QueueTasksResponse)
def read_queue_tasks(
    queue_id: str,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    page: int | None = Query(default=None, ge=1),
    page_size: int | None = Query(default=None, ge=1, le=500),
) -> QueueTasksResponse:
    """Queue summary + (optionally paginated) task list for the Queue Tasks
    page. The summary is always computed over ALL tasks."""
    _require_queue_access(db, queue_id, current_user)
    result = list_queue_tasks(db, queue_id, page=page, page_size=page_size)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Queue not found")
    queue, summary, tasks, pagination = result
    return QueueTasksResponse(
        queue=QueueResponse.model_validate(queue),
        summary=QueueTasksSummary.model_validate(summary),
        tasks=[TaskResponse.model_validate(t) for t in tasks],
        pagination=pagination,
    )


@router.put("/{queue_id}", response_model=QueueResponse)
def edit_queue(
    queue_id: str,
    payload: QueueUpdateRequest,
    _: Annotated[dict, Depends(require_permission("queues"))],
    db: Annotated[Session, Depends(get_db)],
) -> QueueResponse:
    if not get_queue_access_meta(db, queue_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Queue not found")
    updated = update_queue(db, queue_id, payload.model_dump())
    if not updated:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unable to update queue")
    return QueueResponse.model_validate(updated)


@router.patch("/{queue_id}/assign", response_model=QueueResponse)
def assign_queue_to_user(
    queue_id: str,
    payload: QueueAssignRequest,
    current_user: Annotated[dict, Depends(require_permission("queues"))],
    db: Annotated[Session, Depends(get_db)],
) -> QueueResponse:
    updated = assign_queue(db, queue_id, payload.user_id)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Queue or user not found")
    create_audit_log(
        db,
        action="queue_assigned",
        resource_type="queue",
        resource_id=queue_id,
        user_id=str(current_user["id"]),
        details={"assigned_to": payload.user_id, "queue_name": updated["name"]},
    )
    return QueueResponse.model_validate(updated)


@router.put("/{queue_id}/assignees", response_model=QueueResponse)
def set_queue_assignees_endpoint(
    queue_id: str,
    payload: QueueAssigneesRequest,
    current_user: Annotated[dict, Depends(require_permission("queues"))],
    db: Annotated[Session, Depends(get_db)],
) -> QueueResponse:
    """Replace the queue's full assignee pool (multi-user, set semantics)."""
    updated = set_queue_assignees(db, queue_id, payload.user_ids)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Queue not found")
    create_audit_log(
        db,
        action="queue_assignees_set",
        resource_type="queue",
        resource_id=queue_id,
        user_id=str(current_user["id"]),
        details={
            "assigned_to": updated.get("assigned_user_ids", []),
            "count": len(updated.get("assigned_user_ids", [])),
            "queue_name": updated["name"],
        },
    )
    return QueueResponse.model_validate(updated)


@router.patch("/{queue_id}/unassign", response_model=QueueResponse)
def unassign_queue_from_user(
    queue_id: str,
    current_user: Annotated[dict, Depends(require_permission("queues"))],
    db: Annotated[Session, Depends(get_db)],
) -> QueueResponse:
    updated = unassign_queue(db, queue_id)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Queue not found")
    create_audit_log(
        db,
        action="queue_unassigned",
        resource_type="queue",
        resource_id=queue_id,
        user_id=str(current_user["id"]),
        details={"queue_name": updated["name"]},
    )
    return QueueResponse.model_validate(updated)


@router.delete("/{queue_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_queue(
    queue_id: str,
    current_user: Annotated[dict, Depends(require_permission("queues"))],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    existing = get_queue_access_meta(db, queue_id)
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Queue not found")
    delete_queue(db, queue_id)
    create_audit_log(
        db,
        action="queue_deleted",
        resource_type="queue",
        resource_id=queue_id,
        user_id=str(current_user["id"]),
        details={
            "queue_name": existing["name"],
            "annotation_type": existing.get("annotation_type"),
            "linked_qa_queue_id": existing.get("linked_qa_queue_id"),
        },
    )
    return None
