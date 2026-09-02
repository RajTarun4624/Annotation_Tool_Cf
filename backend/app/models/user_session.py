import uuid
from datetime import UTC, datetime
from sqlalchemy import Column, String, DateTime, Boolean, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.models.base import Base

def utc_now() -> datetime:
    return datetime.now(UTC)

class UserSession(Base):
    __tablename__ = "user_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    refresh_token_hash = Column(String, index=True, nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    last_used_at = Column(DateTime, default=utc_now, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    is_revoked = Column(Boolean, default=False, nullable=False)
    replaced_by_session_id = Column(UUID(as_uuid=True), ForeignKey("user_sessions.id", ondelete="SET NULL"), nullable=True)
    user_agent = Column(String, nullable=True)
    ip_address = Column(String, nullable=True)

    # Relationships
    user = relationship("User")
    replaced_by = relationship("UserSession", remote_side=[id])

# Explicit secondary indexes so create_all() matches the alembic migration.
Index("ix_user_sessions_expires_at", UserSession.expires_at)
Index("ix_user_sessions_user_id", UserSession.user_id)
