import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.user import User


def create_audit_log(
    db: Session,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    user_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> AuditLog:
    user_uuid = None
    if user_id:
        try:
            user_uuid = uuid.UUID(user_id)
        except ValueError:
            pass

    log = AuditLog(
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        user_id=user_uuid,
        details=details or {},
        timestamp=datetime.now(UTC),
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log


def list_audit_logs(
    db: Session,
    skip: int = 0,
    limit: int = 100,
    user_id: str | None = None,
    resource_type: str | None = None,
) -> list[dict[str, Any]]:
    query = db.query(AuditLog)
    if user_id:
        try:
            user_uuid = uuid.UUID(user_id)
            query = query.filter(AuditLog.user_id == user_uuid)
        except ValueError:
            pass
    if resource_type:
        query = query.filter(AuditLog.resource_type == resource_type)

    logs = query.order_by(AuditLog.timestamp.desc()).offset(skip).limit(limit).all()

    # Resolve all actor names in one batched query instead of one per row —
    # this list is polled by every open dashboard tab.
    actor_ids = {log.user_id for log in logs if log.user_id}
    names_by_id: dict[Any, str] = {}
    if actor_ids:
        for uid, full_name in db.query(User.id, User.full_name).filter(User.id.in_(actor_ids)):
            names_by_id[uid] = full_name

    results = []
    for log in logs:
        user_name = names_by_id.get(log.user_id, "System") if log.user_id else "System"

        results.append({
            "id": str(log.id),
            "action": log.action,
            "resource_type": log.resource_type,
            "resource_id": log.resource_id,
            "user_id": str(log.user_id) if log.user_id else None,
            "user_name": user_name,
            "details": log.details,
            "timestamp": log.timestamp,
        })
    return results
