import uuid
from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.models.base import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class Task(Base):
    """One prompt to annotate inside a production queue.

    status: pending (0 submissions) | active (>= 1 draft/submission, < required)
            | submitted (awaiting QA) | approved (finalised) | returned (QA sent back)
            (legacy names paused / skipped / declined / rejected are still accepted)
    environment: production | qa (copied from the owning queue's annotation_type)

    A task always belongs to its production queue (``queue_id``); once enough
    annotators have submitted it is ALSO linked to the QA queue
    (``qa_queue_id``) where reviewers finalise it. The customer JSON record is
    stored in ``final_record`` when approved.
    """

    __tablename__ = "tasks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    queue_id = Column(UUID(as_uuid=True), ForeignKey("queues.id", ondelete="CASCADE"), nullable=False)
    # Legacy file columns (unused for prompt tasks; kept nullable).
    file_url = Column(String, nullable=True)
    file_name = Column(String, nullable=True)
    file_type = Column(String, nullable=True)
    batch_name = Column(String, nullable=True)
    status = Column(String, default="pending")
    environment = Column(String, default="production")
    assigned_to = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    assigned_to_name = Column(String, nullable=True)
    submitted_at = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=True)
    paused_at = Column(DateTime, nullable=True)
    annotation_data = Column(JSONB, default=dict)
    draft_data = Column(JSONB, default=dict)
    annotation_version = Column(Integer, default=1)
    annotation_history = Column(JSONB, default=list)
    timer_seconds = Column(Integer, default=7200)
    elapsed_seconds = Column(Integer, default=0)
    declined_reason = Column(String, default="")
    qa_notes = Column(String, default="")
    submitted_by = Column(String, default="")
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    # -- Prompt-attack annotation (SPEC2 section 3) --------------------------
    dataset = Column(String, nullable=True)                 # customer dataset id, e.g. general_text_0122
    input_text = Column(Text, nullable=True)                # the prompt
    sequence = Column(Integer, default=0)                   # 1-based order inside the queue
    source = Column(String, default="real_user")
    meta_data = Column(JSONB, default=dict)                 # seed values from the sheet
    submitted_count = Column(Integer, default=0)            # annotations with status "submitted"
    final_data = Column(JSONB, nullable=True)               # QA's final annotation (data shape)
    final_record = Column(JSONB, nullable=True)             # customer JSON record (build_record)
    finalized_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    finalized_by_name = Column(String, nullable=True)
    finalized_at = Column(DateTime, nullable=True)
    qa_queue_id = Column(UUID(as_uuid=True), ForeignKey("queues.id", ondelete="SET NULL"), nullable=True)

    # Relationships
    queue = relationship("Queue", back_populates="tasks", foreign_keys=[queue_id])
    qa_queue = relationship("Queue", foreign_keys=[qa_queue_id])
    assignee = relationship("User", foreign_keys=[assigned_to])
    finalizer = relationship("User", foreign_keys=[finalized_by])
    annotations = relationship(
        "TaskAnnotation",
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="[TaskAnnotation.submitted_at.asc().nulls_last(), TaskAnnotation.created_at.asc()]",
    )


# Explicit indexes for the hot list/filter paths.
Index("ix_tasks_status", Task.status)
Index("ix_tasks_created_at", Task.created_at)
Index("ix_tasks_submitted_at", Task.submitted_at)
Index("ix_tasks_started_at", Task.started_at)
Index("ix_tasks_queue_id", Task.queue_id)
Index("ix_tasks_batch_name", Task.batch_name)
Index("ix_tasks_environment", Task.environment)
Index("ix_tasks_dataset", Task.dataset)
Index("ix_tasks_qa_queue_id", Task.qa_queue_id)
