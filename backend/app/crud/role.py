import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.user import Role
from app.schemas.pagination import paginate_query


def _serialize_role(role: Role) -> dict[str, Any]:
    now = datetime.now(UTC)
    created_at = role.created_at or now
    return {
        "id": str(role.id),
        "name": role.name,
        "description": role.description or "",
        "is_active": role.is_active,
        "permissions": sorted(role.permissions or []),
        "created_at": created_at,
        "updated_at": role.updated_at or created_at,
    }


def list_roles(
    db: Session,
    search: str | None = None,
    page: int | None = None,
    page_size: int | None = None,
) -> tuple[list[dict[str, Any]], int, int, int]:
    """Return (items, total, page, page_size). Full set in one page when
    page/page_size are None."""
    query = db.query(Role)
    if search:
        term = f"%{search.strip().lower()}%"
        query = query.filter(
            func.lower(Role.name).like(term)
            | func.lower(func.coalesce(Role.description, "")).like(term)
        )
    query = query.order_by(Role.name.asc())
    roles, total, eff_page, eff_size = paginate_query(query, page, page_size)
    items = [_serialize_role(role) for role in roles]
    return items, total, eff_page, eff_size


def get_role_by_id(db: Session, role_id: str) -> dict[str, Any] | None:
    try:
        role_uuid = uuid.UUID(role_id)
    except ValueError:
        return None
    role = db.query(Role).filter(Role.id == role_uuid).first()
    return _serialize_role(role) if role else None


def get_role_document_by_id(db: Session, role_id: str) -> Role | None:
    try:
        role_uuid = uuid.UUID(role_id)
    except ValueError:
        return None
    return db.query(Role).filter(Role.id == role_uuid).first()


def get_role_by_name(db: Session, role_name: str) -> dict[str, Any] | None:
    role = db.query(Role).filter(func.lower(Role.name) == role_name.lower()).first()
    return _serialize_role(role) if role else None


def create_role(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now(UTC)
    role = Role(
        name=payload["name"].strip(),
        description=payload["description"].strip(),
        permissions=sorted(set(payload.get("permissions", []))),
        is_active=payload.get("is_active", True),
        created_at=now,
        updated_at=now,
    )
    db.add(role)
    db.commit()
    db.refresh(role)
    return _serialize_role(role)


def update_role(db: Session, role_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    try:
        role_uuid = uuid.UUID(role_id)
    except ValueError:
        return None
    
    role = db.query(Role).filter(Role.id == role_uuid).first()
    if not role:
        return None

    role.name = payload["name"].strip()
    role.description = payload["description"].strip()
    role.permissions = sorted(set(payload.get("permissions", [])))
    role.is_active = payload.get("is_active", True)
    role.updated_at = datetime.now(UTC)
    
    db.commit()
    db.refresh(role)
    return _serialize_role(role)


def update_role_status(db: Session, role_id: str, is_active: bool) -> dict[str, Any] | None:
    try:
        role_uuid = uuid.UUID(role_id)
    except ValueError:
        return None
    
    role = db.query(Role).filter(Role.id == role_uuid).first()
    if not role:
        return None

    role.is_active = is_active
    role.updated_at = datetime.now(UTC)
    
    db.commit()
    db.refresh(role)
    return _serialize_role(role)
