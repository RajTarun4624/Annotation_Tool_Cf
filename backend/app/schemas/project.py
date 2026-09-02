from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


MediaType = Literal["image", "video", "text", "audio", "document", "multimodal"]
ProjectStatus = Literal["active", "completed", "archived"]


class ProjectCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    description: str = Field(default="", max_length=1000)
    media_type: MediaType = "image"
    status: ProjectStatus = "active"
    assigned_user_ids: list[str] = Field(default_factory=list)


class ProjectUpdateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    description: str = Field(default="", max_length=1000)
    media_type: MediaType = "image"
    status: ProjectStatus = "active"
    assigned_user_ids: list[str] = Field(default_factory=list)


class ProjectResponse(BaseModel):
    id: str
    name: str
    description: str
    media_type: str
    status: str
    assigned_user_ids: list[str] = Field(default_factory=list)
    assigned_users: list[dict] = Field(default_factory=list)
    total_queues: int = 0
    created_by: str | None = None
    created_by_name: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
