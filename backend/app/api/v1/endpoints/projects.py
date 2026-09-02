from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import require_permission
from app.crud.project import create_project, delete_project, get_project_by_id, list_projects, update_project
from app.schemas.pagination import Page
from app.schemas.project import ProjectCreateRequest, ProjectResponse, ProjectUpdateRequest

router = APIRouter()


@router.get("/", response_model=Page[ProjectResponse])
def read_projects(
    _: Annotated[dict, Depends(require_permission("projects"))],
    db: Annotated[Session, Depends(get_db)],
    search: str | None = Query(default=None),
    page: int | None = Query(default=None, ge=1),
    page_size: int | None = Query(default=None, ge=1, le=500),
) -> Page[ProjectResponse]:
    items, total, eff_page, eff_size = list_projects(db, search=search, page=page, page_size=page_size)
    return Page[ProjectResponse](
        items=[ProjectResponse.model_validate(p) for p in items],
        total=total, page=eff_page, page_size=eff_size,
    )


@router.get("/{project_id}", response_model=ProjectResponse)
def read_project(
    project_id: str,
    _: Annotated[dict, Depends(require_permission("projects"))],
    db: Annotated[Session, Depends(get_db)],
) -> ProjectResponse:
    project = get_project_by_id(db, project_id)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return ProjectResponse.model_validate(project)


@router.post("/", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
def add_project(
    payload: ProjectCreateRequest,
    current_user: Annotated[dict, Depends(require_permission("projects"))],
    db: Annotated[Session, Depends(get_db)],
) -> ProjectResponse:
    created = create_project(db, payload.model_dump(), current_user["id"])
    return ProjectResponse.model_validate(created)


@router.put("/{project_id}", response_model=ProjectResponse)
def edit_project(
    project_id: str,
    payload: ProjectUpdateRequest,
    _: Annotated[dict, Depends(require_permission("projects"))],
    db: Annotated[Session, Depends(get_db)],
) -> ProjectResponse:
    existing = get_project_by_id(db, project_id)
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    updated = update_project(db, project_id, payload.model_dump())
    if not updated:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unable to update project")
    return ProjectResponse.model_validate(updated)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_project(
    project_id: str,
    _: Annotated[dict, Depends(require_permission("projects"))],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    existing = get_project_by_id(db, project_id)
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    delete_project(db, project_id)
