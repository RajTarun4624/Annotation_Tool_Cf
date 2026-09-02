import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session
from sqlalchemy import func, or_

from app.core.security import get_password_hash
from app.models.user import User, Role
from app.schemas.pagination import paginate_query


def _serialize_assigned_role(role: Role | None) -> dict[str, Any] | None:
    if not role:
        return None
    return {
        "id": str(role.id),
        "name": role.name,
        "description": role.description or "",
        "is_active": role.is_active,
        "permissions": sorted(role.permissions or []),
    }


def _serialize_user(user: User) -> dict[str, Any]:
    assigned_role = _serialize_assigned_role(user.role)
    return {
        "id": str(user.id),
        "full_name": user.full_name,
        "email": user.email,
        "is_active": user.is_active,
        "created_at": user.created_at,
        "updated_at": user.updated_at or user.created_at,
        "role_id": str(user.role_id) if user.role_id else None,
        "role_name": assigned_role["name"] if assigned_role else None,
        "permissions": assigned_role["permissions"] if assigned_role else [],
        "assigned_role": assigned_role,
        "hashed_password": user.hashed_password,
    }


def get_user_by_email(db: Session, email: str) -> dict[str, Any] | None:
    user = db.query(User).filter(User.email == email.lower()).first()
    if not user:
        return None
    return _serialize_user(user)


def get_user_by_id(db: Session, user_id: str) -> dict[str, Any] | None:
    try:
        user_uuid = uuid.UUID(user_id)
    except ValueError:
        return None
    user = db.query(User).filter(User.id == user_uuid).first()
    if not user:
        return None
    return _serialize_user(user)


def list_users(
    db: Session,
    search: str | None = None,
    page: int | None = None,
    page_size: int | None = None,
) -> tuple[list[dict[str, Any]], int, int, int]:
    """Return (items, total, page, page_size). Searches name, email and role
    name. Full set in one page when page/page_size are None."""
    query = db.query(User)
    if search:
        term = f"%{search.strip().lower()}%"
        # Outer-join Role so users without a role still match name/email.
        query = query.outerjoin(Role, User.role_id == Role.id).filter(
            or_(
                func.lower(User.full_name).like(term),
                func.lower(User.email).like(term),
                func.lower(func.coalesce(Role.name, "")).like(term),
            )
        )
    query = query.order_by(User.created_at.asc())
    users, total, eff_page, eff_size = paginate_query(query, page, page_size)
    items = [_serialize_user(user) for user in users]
    return items, total, eff_page, eff_size


def create_user(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now(UTC)
    role_id = uuid.UUID(payload["role_id"]) if payload.get("role_id") else None
    
    user = User(
        full_name=payload["full_name"].strip(),
        email=payload["email"].lower(),
        hashed_password=get_password_hash(payload["password"]),
        role_id=role_id,
        is_active=payload.get("is_active", True),
        created_at=now,
        updated_at=now,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return _serialize_user(user)


def update_user(db: Session, user_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    try:
        user_uuid = uuid.UUID(user_id)
        role_uuid = uuid.UUID(payload["role_id"]) if payload.get("role_id") else None
    except ValueError:
        return None

    user = db.query(User).filter(User.id == user_uuid).first()
    if not user:
        return None

    user.full_name = payload["full_name"].strip()
    user.email = payload["email"].lower()
    user.role_id = role_uuid
    user.is_active = payload.get("is_active", True)
    user.updated_at = datetime.now(UTC)

    if payload.get("password"):
        user.hashed_password = get_password_hash(payload["password"])

    db.commit()
    db.refresh(user)
    return _serialize_user(user)


def update_user_status(db: Session, user_id: str, is_active: bool) -> dict[str, Any] | None:
    try:
        user_uuid = uuid.UUID(user_id)
    except ValueError:
        return None

    user = db.query(User).filter(User.id == user_uuid).first()
    if not user:
        return None

    user.is_active = is_active
    user.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(user)
    return _serialize_user(user)
