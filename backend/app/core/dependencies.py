from collections.abc import Callable
from typing import Annotated, Any

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.core.cache import user_cache
from app.core.config import settings
from app.core.database import get_db
from app.core.security import ALGORITHM
from app.crud.user import get_user_by_id

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/login")


def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError as exc:
        raise credentials_exception from exc

    # Every request pays this lookup; a short per-process cache turns the
    # user + role queries into a dict hit. Deactivation / permission changes
    # take effect within USER_CACHE_SECONDS.
    user = user_cache.get(user_id)
    if user is None:
        user = get_user_by_id(db, user_id)
        if user:
            user_cache.set(user_id, user, settings.USER_CACHE_SECONDS)
    if not user:
        raise credentials_exception
    if not user.get("is_active", True):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Inactive user")
    assigned_role = user.get("assigned_role")
    if assigned_role and not assigned_role.get("is_active", True):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Assigned role is inactive")
    return user


def require_permission(permission: str) -> Callable[..., dict[str, Any]]:
    def dependency(current_user: Annotated[dict[str, Any], Depends(get_current_user)]) -> dict[str, Any]:
        permissions = set(current_user.get("permissions", []))
        if permission not in permissions:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return current_user

    return dependency
