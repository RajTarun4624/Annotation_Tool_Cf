from pydantic import BaseModel, EmailStr

from app.schemas.user import AssignedRoleResponse, UserProfileResponse


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserProfileResponse
    role: AssignedRoleResponse | None = None
    permissions: list[str]
