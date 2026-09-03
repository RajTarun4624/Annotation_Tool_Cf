import uuid
from datetime import UTC, datetime
from sqlalchemy import Column, String, DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from app.models.base import Base

def utc_now() -> datetime:
    return datetime.now(UTC)

class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    action = Column(String, nullable=False)
    resource_type = Column(String)
    resource_id = Column(String)
    details = Column(JSONB, default=dict)
    timestamp = Column(DateTime, default=utc_now)

    user = relationship("User")


# The dashboard reads the newest rows on every poll; without this the sort is a full scan.
Index("ix_audit_logs_timestamp", AuditLog.timestamp)
