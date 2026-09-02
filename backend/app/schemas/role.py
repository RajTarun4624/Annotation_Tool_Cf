from datetime import datetime

from pydantic import BaseModel, Field


class RoleBase(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    description: str = Field(default="", min_length=0, max_length=240)
    permissions: list[str] = Field(default_factory=list)


class RoleCreateRequest(RoleBase):
    is_active: bool = True


class RoleUpdateRequest(RoleBase):
    is_active: bool = True


class RoleStatusUpdateRequest(BaseModel):
    is_active: bool


class RoleResponse(BaseModel):
    id: str
    name: str
    description: str
    is_active: bool
    permissions: list[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class RolePermissionsResponse(BaseModel):
    role_id: str
    permissions: list[str]
