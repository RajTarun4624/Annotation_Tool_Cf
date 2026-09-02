from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.crud.audit_log import list_audit_logs
from app.models.project import Project
from app.models.queue import Queue
from app.models.task import Task
from app.models.user import User

router = APIRouter()


@router.get("/stats")
def get_dashboard_stats(
    _: Annotated[dict, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    total_active_users = db.query(User).filter(User.is_active.is_(True)).count()
    total_projects = db.query(Project).count()
    total_queues = db.query(Queue).count()
    # A user is "working" when they hold at least one task that is active.
    currently_working_users = (
        db.query(func.count(func.distinct(Task.assigned_to)))
        .filter(Task.status == "active", Task.assigned_to.isnot(None))
        .scalar()
    ) or 0

    return {
        "total_active_users": total_active_users,
        "total_projects": total_projects,
        "total_queues": total_queues,
        "currently_working_users": int(currently_working_users),
    }


@router.get("/active-queues")
def get_active_queues(
    _: Annotated[dict, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[dict[str, Any]]:
    """Single statement: project/user names come from JOINs and the task
    progress counters from a grouped subquery over the relational tasks table
    (this endpoint is polled by every open dashboard tab)."""
    rows = db.execute(
        text(
            """
            SELECT q.id::text AS id,
                   q.name,
                   p.name AS project_name,
                   u.full_name AS assigned_user_name,
                   q.sla_hours,
                   q.priority,
                   q.status,
                   COALESCE(tc.total, 0) AS total,
                   COALESCE(tc.done, 0) AS done
            FROM queues q
            LEFT JOIN projects p ON p.id = q.project_id
            LEFT JOIN users u ON u.id = q.assigned_user_id
            LEFT JOIN (
                SELECT t.queue_id,
                       COUNT(*) AS total,
                       COUNT(*) FILTER (
                           WHERE t.status IN ('submitted', 'approved')
                       ) AS done
                FROM tasks t
                GROUP BY t.queue_id
            ) tc ON tc.queue_id = q.id
            WHERE q.status = 'active'
            ORDER BY q.created_at DESC
            LIMIT 20
            """
        )
    ).mappings()

    result = []
    for row in rows:
        total = int(row["total"] or 0)
        done = int(row["done"] or 0)
        result.append({
            "id": row["id"],
            "name": row["name"],
            "project_name": row["project_name"],
            "progress": int(done / total * 100) if total > 0 else 0,
            "total_tasks": total,
            "done_tasks": done,
            "sla_hours": row["sla_hours"] or 24,
            "priority": row["priority"] or "medium",
            "status": row["status"] or "inactive",
            "assigned_user_name": row["assigned_user_name"],
        })
    return result


@router.get("/live-activity")
def get_live_activity(
    _: Annotated[dict, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[dict[str, Any]]:
    return list_audit_logs(db, limit=20)
