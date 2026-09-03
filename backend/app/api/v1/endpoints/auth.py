import random
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.ratelimit import login_limiter
from app.core.security import get_password_hash, verify_password
from app.crud.user import get_user_by_email, get_user_by_id
from app.models.user import User
from app.repositories.user_session_repository import UserSessionRepository
from app.schemas.auth import LoginRequest, TokenResponse
from app.schemas.user import UserProfileResponse
from app.services.auth_service import AuthService

router = APIRouter()


def _set_refresh_cookie(response: Response, value: str) -> None:
    response.set_cookie(
        key="refresh_token",
        value=value,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="lax",
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600,
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key="refresh_token",
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="lax",
    )


@router.post("/login", response_model=TokenResponse)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> TokenResponse:
    # Rate limit BEFORE the password hash so a brute-force attempt cannot
    # monopolise the thread pool at shift start.
    client_ip = request.client.host if request.client else "?"
    limit_key = f"{client_ip}|{payload.email.lower()}"
    if not login_limiter.allow(limit_key):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Please wait a minute and try again.",
        )
    user = get_user_by_email(db, payload.email.lower())
    if not user or not verify_password(payload.password, user["hashed_password"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    login_limiter.reset(limit_key)
    # Housekeeping: drop long-dead sessions now and then (indexed DELETE).
    if random.random() < 0.02:
        UserSessionRepository.cleanup_expired_sessions(db, grace_days=1)
    if not user["is_active"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Inactive user")
    assigned_role = user.get("assigned_role")
    if assigned_role and not assigned_role.get("is_active", True):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Assigned role is inactive")

    user_uuid = uuid.UUID(str(user["id"]))
    user_agent = request.headers.get("user-agent")
    ip_address = request.client.host if request.client else None

    access_token, refresh_token_raw = AuthService.login_session(
        db,
        user_id=user_uuid,
        user_agent=user_agent,
        ip_address=ip_address,
    )
    db.commit()

    _set_refresh_cookie(response, refresh_token_raw)

    profile = UserProfileResponse.model_validate(user)
    return TokenResponse(
        access_token=access_token,
        user=profile,
        role=profile.assigned_role,
        permissions=profile.permissions,
    )


@router.get("/me", response_model=UserProfileResponse)
def read_logged_in_user(
    current_user: Annotated[dict, Depends(get_current_user)],
) -> UserProfileResponse:
    return UserProfileResponse.model_validate(current_user)


class RefreshTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


@router.post("/refresh", response_model=RefreshTokenResponse)
def refresh(
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> RefreshTokenResponse:
    refresh_token = request.cookies.get("refresh_token")
    if not refresh_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token missing")

    user_agent = request.headers.get("user-agent")
    ip_address = request.client.host if request.client else None

    new_access_token, new_refresh_token = AuthService.rotate_session(
        db,
        refresh_token_raw=refresh_token,
        user_agent=user_agent,
        ip_address=ip_address,
    )
    db.commit()

    _set_refresh_cookie(response, new_refresh_token)
    return RefreshTokenResponse(access_token=new_access_token)


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    refresh_token = request.cookies.get("refresh_token")
    if refresh_token:
        AuthService.logout_session(db, refresh_token)

    _clear_refresh_cookie(response)
    return {"success": True, "message": "Successfully logged out"}


@router.post("/logout-all")
def logout_all(
    current_user: Annotated[dict, Depends(get_current_user)],
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    user_uuid = uuid.UUID(str(current_user["id"]))
    AuthService.logout_all_sessions(db, user_uuid)

    _clear_refresh_cookie(response)
    return {"success": True, "message": "Successfully logged out from all devices"}


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


@router.post("/change-password")
def change_password(
    payload: ChangePasswordRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Let the signed-in user rotate their own password. Other sessions are
    left untouched — the user can revoke them via /logout-all."""
    user = get_user_by_id(db, str(current_user["id"]))
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if not verify_password(payload.current_password, user["hashed_password"]):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")

    row = db.query(User).filter(User.id == uuid.UUID(str(user["id"]))).first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    row.hashed_password = get_password_hash(payload.new_password)
    row.updated_at = datetime.now(UTC)
    db.commit()

    return {"success": True, "message": "Password updated."}


class SessionItem(BaseModel):
    session_id: str
    created_at: str
    last_used_at: str
    user_agent: str
    ip_address: str
    is_current: bool


@router.get("/sessions", response_model=list[SessionItem])
def list_sessions(
    request: Request,
    current_user: Annotated[dict, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[SessionItem]:
    user_uuid = uuid.UUID(str(current_user["id"]))
    refresh_token = request.cookies.get("refresh_token")

    sessions = AuthService.list_active_sessions(db, user_uuid, refresh_token)
    return [SessionItem.model_validate(s) for s in sessions]
