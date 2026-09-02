import uuid
from datetime import UTC, datetime
from sqlalchemy import Column, String, DateTime, ForeignKey, Table
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.models.base import Base

def utc_now() -> datetime:
    return datetime.now(UTC)

# Association table for Project <-> User (Assigned Users)
project_assigned_users = Table(
    "project_assigned_users",
    Base.metadata,
    Column("project_id", UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True),
    Column("user_id", UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
)

class Project(Base):
    __tablename__ = "projects"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    description = Column(String)
    media_type = Column(String, default="image")
    status = Column(String, default="active")
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    # Relationships
    assigned_users = relationship("User", secondary=project_assigned_users)
    creator = relationship("User", foreign_keys=[created_by])
    queues = relationship("Queue", back_populates="project")
