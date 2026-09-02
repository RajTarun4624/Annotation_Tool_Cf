import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.models.base import Base


class FeatureKey(str, enum.Enum):
    DASHBOARD = "dashboard"
    PROJECTS = "projects"
    QUEUES = "queues"
    TASKS = "tasks"
    ROLES = "roles"
    USERS = "users"
    ANNOTATION_QUEUES = "annotation_queues"
    PROFILE = "profile"


# Seeded into the `features` table on startup (see services/bootstrap.py) and
# granted in full to the Administrator role. `order` drives the sidebar order.
DEFAULT_FEATURES: list[dict[str, object]] = [
    {
        "key": FeatureKey.DASHBOARD.value,
        "name": "Dashboard",
        "description": "Overview metrics and active queues.",
        "icon": "DashboardOutlined",
        "order": 1,
    },
    {
        "key": FeatureKey.PROJECTS.value,
        "name": "Projects",
        "description": "Organize queues under delivery projects.",
        "icon": "ProjectOutlined",
        "order": 2,
    },
    {
        "key": FeatureKey.QUEUES.value,
        "name": "Queues",
        "description": "Create queues, assign annotators and track progress.",
        "icon": "InboxOutlined",
        "order": 3,
    },
    {
        "key": FeatureKey.TASKS.value,
        "name": "Tasks",
        "description": "Monitor task progress and review submissions.",
        "icon": "UnorderedListOutlined",
        "order": 4,
    },
    {
        "key": FeatureKey.ROLES.value,
        "name": "Roles",
        "description": "Manage roles, permissions, and activation state.",
        "icon": "SafetyCertificateOutlined",
        "order": 5,
    },
    {
        "key": FeatureKey.USERS.value,
        "name": "Users",
        "description": "Manage users, assigned roles, and access state.",
        "icon": "TeamOutlined",
        "order": 6,
    },
    {
        "key": FeatureKey.ANNOTATION_QUEUES.value,
        "name": "Annotation Queues",
        "description": "Queues assigned to you for annotation.",
        "icon": "FormOutlined",
        "order": 7,
    },
    {
        "key": FeatureKey.PROFILE.value,
        "name": "Profile",
        "description": "View account information and active sessions.",
        "icon": "UserOutlined",
        "order": 8,
    },
]


def utc_now() -> datetime:
    return datetime.now(UTC)


class Feature(Base):
    __tablename__ = "features"
    key = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    description = Column(String)
    icon = Column(String)
    order = Column(Integer, default=0)


class Role(Base):
    __tablename__ = "roles"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, unique=True, nullable=False)
    description = Column(String)
    is_active = Column(Boolean, default=True)
    permissions = Column(JSONB, default=list)  # List of feature keys
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    users = relationship("User", back_populates="role")


class User(Base):
    __tablename__ = "users"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    full_name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    role_id = Column(UUID(as_uuid=True), ForeignKey("roles.id"), nullable=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    role = relationship("Role", back_populates="users")
