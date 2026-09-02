import uuid
from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Table
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.models.base import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


# Association table for Queue <-> User (many annotators can share one queue's
# task pool). Mirrors `project_assigned_users`. The extra index on `user_id`
# keeps the per-user "my queues" lookup fast when many annotators hit the
# list endpoint concurrently.
queue_assigned_users = Table(
    "queue_assigned_users",
    Base.metadata,
    Column("queue_id", UUID(as_uuid=True), ForeignKey("queues.id", ondelete="CASCADE"), primary_key=True),
    Column("user_id", UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Index("ix_queue_assigned_users_user_id", "user_id"),
)


class Queue(Base):
    """A batch of annotation work.

    Tasks live ONLY in the relational `tasks` table (models/task.py); there is
    no JSONB mirror and no flush-time sync.

    status: inactive (nobody assigned) -> active (assigned) -> completed
    annotation_type: production | qa
    required_annotators: annotators that must submit each task (default 3)
    source_name: file name / URL the tasks were imported from (nullable)
    priority: low | medium | high | critical
    """

    __tablename__ = "queues"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=True)
    task_name = Column(String)
    batch_name = Column(String)
    annotation_type = Column(String, default="production")
    priority = Column(String, default="medium")
    sla_hours = Column(Integer, default=24)
    status = Column(String, default="inactive")
    # Primary assignee: the first / surviving member of `assigned_users`.
    assigned_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    linked_qa_queue_id = Column(UUID(as_uuid=True), ForeignKey("queues.id", ondelete="SET NULL"), nullable=True)
    source_production_queue_id = Column(UUID(as_uuid=True), ForeignKey("queues.id", ondelete="SET NULL"), nullable=True)
    timer_seconds = Column(Integer, default=7200)
    # Number of annotators that must submit before a task moves to QA
    # (production queues; the auto-created QA queue uses 1).
    required_annotators = Column(Integer, nullable=False, default=3, server_default="3")
    # Import source for traceability (SPEC3 section 3): the uploaded file name
    # or the pasted spreadsheet link. Null for queues created without a sheet.
    source_name = Column(String, nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    # Relationships
    project = relationship("Project", back_populates="queues")
    # Tasks OWNED by this (production) queue. Tasks also point at their QA
    # queue through Task.qa_queue_id, hence the explicit foreign_keys.
    tasks = relationship(
        "Task", back_populates="queue", cascade="all, delete-orphan", foreign_keys="Task.queue_id"
    )
    assigned_users = relationship("User", secondary=queue_assigned_users)
    assigned_user = relationship("User", foreign_keys=[assigned_user_id])
    creator = relationship("User", foreign_keys=[created_by])
