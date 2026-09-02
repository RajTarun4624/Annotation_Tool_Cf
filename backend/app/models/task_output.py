import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.models.base import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class TaskOutput(Base):
    """Stores submitted and finalized task annotation details in a dedicated table."""

    __tablename__ = "tasks_output"
    __table_args__ = (
        UniqueConstraint("task_id", "user_id", name="uq_tasks_output_task_user"),
        Index("ix_tasks_output_task_id", "task_id"),
        Index("ix_tasks_output_user_id", "user_id"),
        Index("ix_tasks_output_queue_id", "queue_id"),
        Index("ix_tasks_output_dataset", "dataset"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id = Column(UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    user_name = Column(String, nullable=True)
    queue_id = Column(UUID(as_uuid=True), ForeignKey("queues.id", ondelete="CASCADE"), nullable=True)
    dataset = Column(String, nullable=True)
    input_text = Column(Text, nullable=True)

    data_type = Column(String, nullable=True)
    data_structure = Column(String, nullable=True)
    attack_type = Column(JSONB, default=list)
    attack_subcategory = Column(JSONB, default=list)
    domain = Column(String, nullable=True)
    role = Column(String, nullable=True)
    verified = Column(Boolean, default=False)
    language = Column(String, default="en")
    document_edited = Column(Boolean, default=False)
    source_description = Column(Text, nullable=True)
    severity_j = Column(Integer, default=0)
    severity_i = Column(Integer, default=0)
    severity_l = Column(Integer, default=0)
    intention = Column(String, nullable=True)
    source = Column(String, nullable=True)

    jailbreak = Column(Boolean, default=False)
    prompt_injection = Column(Boolean, default=False)
    prompt_leakage = Column(Boolean, default=False)

    annotation_data = Column(JSONB, default=dict)
    elapsed_seconds = Column(Integer, default=0)
    status = Column(String, default="submitted")
    submitted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    # Relationships
    task = relationship("Task", foreign_keys=[task_id])
    user = relationship("User", foreign_keys=[user_id])
    queue = relationship("Queue", foreign_keys=[queue_id])
