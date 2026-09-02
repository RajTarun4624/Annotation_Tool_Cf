import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.user import User
from app.models.queue import Queue
from app.schemas.pagination import paginate_query


def _serialize_project(project: Project, assigned_users: list[dict] | None = None, total_queues: int = 0, created_by_name: str | None = None) -> dict[str, Any]:
    return {
        "id": str(project.id),
        "name": project.name,
        "description": project.description or "",
        "media_type": project.media_type or "image",
        "status": project.status or "active",
        "assigned_user_ids": [str(user.id) for user in project.assigned_users],
        "assigned_users": assigned_users or [],
        "total_queues": total_queues,
        "created_by": str(project.created_by) if project.created_by else None,
        "created_by_name": created_by_name,
        "created_at": project.created_at,
        "updated_at": project.updated_at or project.created_at,
    }


def _enrich_project(db: Session, project: Project) -> dict[str, Any]:
    assigned_users = []
    for user in project.assigned_users:
        assigned_users.append({"id": str(user.id), "full_name": user.full_name, "email": user.email})

    total_queues = db.query(Queue).filter(Queue.project_id == project.id).count()

    created_by_name = None
    if project.created_by:
        creator = db.query(User).filter(User.id == project.created_by).first()
        if creator:
            created_by_name = creator.full_name

    return _serialize_project(project, assigned_users, total_queues, created_by_name)


def list_projects(
    db: Session,
    search: str | None = None,
    page: int | None = None,
    page_size: int | None = None,
) -> tuple[list[dict[str, Any]], int, int, int]:
    """Return (items, total, page, page_size). Full set in one page when
    page/page_size are None."""
    query = db.query(Project)
    if search:
        term = f"%{search.strip().lower()}%"
        query = query.filter(
            func.lower(Project.name).like(term)
            | func.lower(func.coalesce(Project.description, "")).like(term)
        )
    query = query.order_by(Project.created_at.desc())
    projects, total, eff_page, eff_size = paginate_query(query, page, page_size)
    items = [_enrich_project(db, project) for project in projects]
    return items, total, eff_page, eff_size


def get_project_by_id(db: Session, project_id: str) -> dict[str, Any] | None:
    try:
        project_uuid = uuid.UUID(project_id)
    except ValueError:
        return None
    project = db.query(Project).filter(Project.id == project_uuid).first()
    if not project:
        return None
    return _enrich_project(db, project)


def create_project(db: Session, payload: dict[str, Any], created_by: str) -> dict[str, Any]:
    now = datetime.now(UTC)

    assigned_user_ids = []
    for uid in payload.get("assigned_user_ids", []):
        try:
            assigned_user_ids.append(uuid.UUID(uid))
        except ValueError:
            continue

    created_by_uuid = None
    try:
        created_by_uuid = uuid.UUID(created_by)
    except ValueError:
        pass

    project = Project(
        name=payload["name"].strip(),
        description=payload.get("description", "").strip(),
        media_type=payload.get("media_type", "image"),
        status=payload.get("status", "active"),
        created_by=created_by_uuid,
        created_at=now,
        updated_at=now,
    )

    if assigned_user_ids:
        users = db.query(User).filter(User.id.in_(assigned_user_ids)).all()
        project.assigned_users = users

    db.add(project)
    db.commit()
    db.refresh(project)
    return _enrich_project(db, project)


def update_project(db: Session, project_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    try:
        project_uuid = uuid.UUID(project_id)
    except ValueError:
        return None

    project = db.query(Project).filter(Project.id == project_uuid).first()
    if not project:
        return None

    assigned_user_ids = []
    for uid in payload.get("assigned_user_ids", []):
        try:
            assigned_user_ids.append(uuid.UUID(uid))
        except ValueError:
            continue

    now = datetime.now(UTC)
    project.name = payload["name"].strip()
    project.description = payload.get("description", "").strip()
    project.media_type = payload.get("media_type", "image")
    project.status = payload.get("status", "active")
    project.updated_at = now

    if assigned_user_ids:
        users = db.query(User).filter(User.id.in_(assigned_user_ids)).all()
        project.assigned_users = users
    else:
        project.assigned_users = []

    db.commit()
    db.refresh(project)
    return _enrich_project(db, project)


def delete_project(db: Session, project_id: str) -> bool:
    try:
        project_uuid = uuid.UUID(project_id)
    except ValueError:
        return False

    project = db.query(Project).filter(Project.id == project_uuid).first()
    if not project:
        return False

    db.delete(project)
    db.commit()
    return True
