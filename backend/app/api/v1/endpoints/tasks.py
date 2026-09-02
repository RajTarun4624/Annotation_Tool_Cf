from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.schemas.pagination import Page
from app.services.task_service import TaskService

router = APIRouter()

# Either console (Tasks or Queues) may read the task list.
_CONSOLE_PERMISSIONS = {"tasks", "queues"}


class TaskItemResponse(BaseModel):
    id: str
    queue_id: str
    task_name: str
    file_name: str | None = None
    batch_name: str
    queue_name: str
    environment: str
    status: str
    aht: str
    elapsed_seconds: int
    created_at: str | None = None
    started_at: str | None = None
    submitted_at: str | None = None
    submitted_by: str
    # SPEC2 §5.4 additions
    dataset: str = ""
    input_preview: str = ""
    submitted_count: int = 0
    required_annotators: int = 3
    finalized_by_name: str | None = None
    finalized_at: str | None = None


def _require_console_access(current_user: dict, detail: str) -> None:
    permissions = set(current_user.get("permissions", []))
    if not permissions & _CONSOLE_PERMISSIONS:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


@router.get("/", response_model=Page[TaskItemResponse])
def read_tasks(
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    search: str | None = Query(default=None),
    status: str | None = Query(default=None),
    environment: str | None = Query(default=None),
    queue: str | None = Query(default=None),
    sort_by: str | None = Query(default=None),
    sort_order: str | None = Query(default=None),
    page: int | None = Query(default=None, ge=1),
    page_size: int | None = Query(default=None, ge=1, le=500),
) -> Page[TaskItemResponse]:
    _require_console_access(current_user, "Insufficient permissions to view tasks console.")

    items, total, eff_page, eff_size = TaskService.list_tasks(
        db,
        search=search,
        status=status,
        environment=environment,
        queue=queue,
        sort_by=sort_by,
        sort_order=sort_order,
        page=page,
        page_size=page_size,
    )
    return Page[TaskItemResponse](
        items=[TaskItemResponse.model_validate(item) for item in items],
        total=total,
        page=eff_page,
        page_size=eff_size,
    )


@router.get("/export")
def export_tasks(
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    search: str | None = Query(default=None),
    status: str | None = Query(default=None),
    environment: str | None = Query(default=None),
    queue: str | None = Query(default=None),
    sort_by: str | None = Query(default=None),
    sort_order: str | None = Query(default=None),
):
    _require_console_access(current_user, "Insufficient permissions to export tasks.")

    xlsx_bytes = TaskService.export_tasks_to_excel(
        db,
        search=search,
        status=status,
        environment=environment,
        queue=queue,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="tasks_report.xlsx"'},
    )


@router.get("/queue-names", response_model=list[str])
def read_queue_names(
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[str]:
    """Distinct queue names for the Tasks console's queue filter dropdown."""
    _require_console_access(current_user, "Insufficient permissions to view tasks console.")
    return TaskService.get_queue_names(db)


@router.post("/{task_id}/reinject")
def reinject_task(
    task_id: str,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    _require_console_access(current_user, "Insufficient permissions to reinject tasks.")

    success = TaskService.reinject_task(db, task_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found or unable to reinject.",
        )
    return {"success": True, "message": "Task reinjected successfully."}
