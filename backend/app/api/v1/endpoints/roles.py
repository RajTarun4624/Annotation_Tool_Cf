from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import require_permission
from app.crud.role import create_role, get_role_by_id, get_role_by_name, list_roles, update_role, update_role_status
from app.schemas.pagination import Page
from app.schemas.role import (
    RoleCreateRequest,
    RolePermissionsResponse,
    RoleResponse,
    RoleStatusUpdateRequest,
    RoleUpdateRequest,
)

router = APIRouter()


@router.get("/", response_model=Page[RoleResponse])
def read_roles(
    _: Annotated[dict, Depends(require_permission("roles"))],
    db: Annotated[Session, Depends(get_db)],
    search: str | None = Query(default=None),
    page: int | None = Query(default=None, ge=1),
    page_size: int | None = Query(default=None, ge=1, le=500),
) -> Page[RoleResponse]:
    items, total, eff_page, eff_size = list_roles(db, search=search, page=page, page_size=page_size)
    return Page[RoleResponse](
        items=[RoleResponse.model_validate(role) for role in items],
        total=total, page=eff_page, page_size=eff_size,
    )


@router.get("/{role_id}", response_model=RoleResponse)
def read_role(
    role_id: str,
    _: Annotated[dict, Depends(require_permission("roles"))],
    db: Annotated[Session, Depends(get_db)],
) -> RoleResponse:
    role = get_role_by_id(db, role_id)
    if not role:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")
    return RoleResponse.model_validate(role)


@router.post("/", response_model=RoleResponse, status_code=status.HTTP_201_CREATED)
def add_role(
    payload: RoleCreateRequest,
    _: Annotated[dict, Depends(require_permission("roles"))],
    db: Annotated[Session, Depends(get_db)],
) -> RoleResponse:
    existing = get_role_by_name(db, payload.name)
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Role name already exists")
    created = create_role(db, payload.model_dump())
    return RoleResponse.model_validate(created)


@router.put("/{role_id}", response_model=RoleResponse)
def edit_role(
    role_id: str,
    payload: RoleUpdateRequest,
    _: Annotated[dict, Depends(require_permission("roles"))],
    db: Annotated[Session, Depends(get_db)],
) -> RoleResponse:
    existing = get_role_by_id(db, role_id)
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")
    duplicate = get_role_by_name(db, payload.name)
    if duplicate and duplicate["id"] != role_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Role name already exists")
    updated = update_role(db, role_id, payload.model_dump())
    if not updated:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unable to update role")
    return RoleResponse.model_validate(updated)


@router.patch("/{role_id}/status", response_model=RoleResponse)
def edit_role_status(
    role_id: str,
    payload: RoleStatusUpdateRequest,
    _: Annotated[dict, Depends(require_permission("roles"))],
    db: Annotated[Session, Depends(get_db)],
) -> RoleResponse:
    updated = update_role_status(db, role_id, payload.is_active)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")
    return RoleResponse.model_validate(updated)


@router.get("/{role_id}/permissions", response_model=RolePermissionsResponse)
def read_role_permissions(
    role_id: str,
    _: Annotated[dict, Depends(require_permission("roles"))],
    db: Annotated[Session, Depends(get_db)],
) -> RolePermissionsResponse:
    role = get_role_by_id(db, role_id)
    if not role:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")
    return RolePermissionsResponse(role_id=role_id, permissions=role["permissions"])
