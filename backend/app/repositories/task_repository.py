import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Session, joinedload

from app.models.queue import Queue
from app.models.task import Task
from app.schemas.pagination import paginate_query


class TaskRepository:
    @staticmethod
    def get_tasks(
        db: Session,
        *,
        search: str | None = None,
        status: str | None = None,
        environment: str | None = None,
        queue: str | None = None,
        sort_by: str | None = None,
        sort_order: str | None = None,
        page: int | None = None,
        page_size: int | None = None,
    ):
        # Join the queue for filtering/searching and eager-load it so the
        # serializer's `task.queue` access never fires a per-row query.
        query = db.query(Task).join(Queue, Task.queue_id == Queue.id).options(
            joinedload(Task.queue)
        )

        # Filtering by environment: where the task currently lives. A task routed to
        # the QA queue (enough submissions, or finalised) counts as 'qa'; everything
        # still being annotated counts as 'production'.
        if environment:
            env = environment.lower()
            if env == "qa":
                query = query.filter(Task.qa_queue_id.isnot(None))
            elif env == "production":
                query = query.filter(Task.qa_queue_id.is_(None))
            else:
                query = query.filter(Task.environment == env)

        # Filtering by queue name — exact match on the queue the task belongs to
        # (the console offers a dropdown of existing queue names).
        if queue:
            query = query.filter(Queue.name == queue)

        # Filtering by status — accepts a single status ("approved") or a
        # comma-separated list ("submitted,approved").
        if status:
            wanted = [s.strip().lower() for s in status.split(",") if s.strip()]
            if len(wanted) == 1:
                query = query.filter(Task.status == wanted[0])
            elif wanted:
                query = query.filter(Task.status.in_(wanted))

        # Searching by dataset id, prompt text, file name, task id (UUID),
        # batch name, task name, queue name
        if search:
            term = f"%{search.strip().lower()}%"
            query = query.filter(
                sa.func.coalesce(Task.dataset, "").ilike(term)
                | sa.func.coalesce(Task.input_text, "").ilike(term)
                | Task.id.cast(sa.String).ilike(term)
                | sa.func.coalesce(Task.file_name, "").ilike(term)
                | sa.func.coalesce(Task.batch_name, "").ilike(term)
                | sa.func.coalesce(Queue.task_name, "").ilike(term)
                | Queue.name.ilike(term)
            )

        # Sorting on: AHT (elapsed_seconds), Created, Started At, Submitted At, Status
        sort_field = None
        if sort_by == "created_at":
            sort_field = Task.created_at
        elif sort_by == "started_at":
            sort_field = Task.started_at
        elif sort_by == "submitted_at":
            sort_field = Task.submitted_at
        elif sort_by == "status":
            sort_field = Task.status
        elif sort_by == "aht":
            sort_field = Task.elapsed_seconds
        elif sort_by == "finalized_at":
            sort_field = Task.finalized_at
        elif sort_by == "dataset":
            sort_field = Task.dataset
        elif sort_by == "sequence":
            sort_field = Task.sequence

        if sort_field is not None:
            if sort_order == "desc":
                query = query.order_by(sort_field.desc().nulls_last(), Task.id.asc())
            else:
                query = query.order_by(sort_field.asc().nulls_last(), Task.id.asc())
        else:
            # Default sorting
            query = query.order_by(Task.created_at.desc(), Task.id.asc())

        items, total, eff_page, eff_size = paginate_query(query, page, page_size)
        return items, total, eff_page, eff_size

    @staticmethod
    def get_queue_names(db: Session) -> list[str]:
        """Distinct, sorted queue names that currently have at least one task —
        used to populate the Tasks console's queue-name filter dropdown."""
        rows = (
            db.query(Queue.name)
            .join(Task, Task.queue_id == Queue.id)
            .filter(Queue.name.isnot(None))
            .distinct()
            .order_by(Queue.name.asc())
            .all()
        )
        return [r[0] for r in rows if r[0]]

    @staticmethod
    def get_task_by_id(db: Session, task_id: str) -> Task | None:
        try:
            task_uuid = uuid.UUID(task_id)
        except (ValueError, TypeError):
            return None
        return db.query(Task).filter(Task.id == task_uuid).first()
