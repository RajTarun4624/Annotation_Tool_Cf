import uuid
from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.models.base import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class TaskAnnotation(Base):
    """One RESPONSE to one task.

    Consensus needs N responses per task, not N distinct people, so the same
    annotator may hold several rows for a task (response 1, 2, ...). At most
    one of them is open (draft/returned) at a time. ``data`` holds the
    annotation JSON described in SPEC2 section 2; derived values (output,
    lengths) are never stored here.

    status: draft | submitted | returned
    """

    __tablename__ = "task_annotations"
    __table_args__ = (
        Index("ix_task_annotations_task_id", "task_id"),
        Index("ix_task_annotations_user_id", "user_id"),
        Index("ix_task_annotations_task_status", "task_id", "status"),
        Index("ix_task_annotations_user_status", "user_id", "status"),
        # At most ONE open response (draft / returned) per user per task. This is
        # what makes a double-clicked or replayed claim harmless: the second
        # insert fails instead of creating a phantom row that holds a slot.
        Index(
            "uq_task_annotations_open",
            "task_id",
            "user_id",
            unique=True,
            postgresql_where=text("status IN ('draft', 'returned')"),
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id = Column(UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    user_name = Column(String, nullable=True)
    status = Column(String, default="draft")
    data = Column(JSONB, default=dict)
    elapsed_seconds = Column(Integer, default=0)
    submitted_at = Column(DateTime, nullable=True)
    # Claim lease: the workspace heartbeats while the task is open. A draft whose
    # last_seen_at is older than CLAIM_LEASE_SECONDS no longer counts as
    # "in flight", so an abandoned browser tab never hides a task from others.
    last_seen_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    # Relationships
    task = relationship("Task", back_populates="annotations")
    user = relationship("User", foreign_keys=[user_id])
