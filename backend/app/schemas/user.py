from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class AssignedRoleResponse(BaseModel):
    id: str
    name: str
    description: str
    is_active: bool
    permissions: list[str]


class UserProfileResponse(BaseModel):
    id: str
    full_name: str
    email: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
    role_id: str | None = None
    role_name: str | None = None
    permissions: list[str] = Field(default_factory=list)
    assigned_role: AssignedRoleResponse | None = None

    model_config = {"from_attributes": True}


class UserSummaryResponse(UserProfileResponse):
    pass


class UserCreateRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    role_id: str
    is_active: bool = True


class UserUpdateRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str | None = Field(default=None, min_length=8, max_length=128)
    role_id: str
    is_active: bool = True


class UserStatusUpdateRequest(BaseModel):
    is_active: bool
