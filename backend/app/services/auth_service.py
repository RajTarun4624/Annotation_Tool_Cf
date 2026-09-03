import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, UTC
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.security import create_access_token
from app.repositories.user_session_repository import UserSessionRepository
from app.crud.audit_log import create_audit_log

class AuthService:
    @staticmethod
    def hash_token(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def login_session(
        db: Session,
        user_id: uuid.UUID,
        user_agent: str | None = None,
        ip_address: str | None = None
    ) -> tuple[str, str]:
        # Generate Access Token (using existing logic)
        access_token = create_access_token(subject=str(user_id))

        # Generate Refresh Token
        refresh_token_raw = secrets.token_urlsafe(64)
        refresh_token_hash = AuthService.hash_token(refresh_token_raw)

        # Set Expiration
        expires_at = datetime.now(UTC).replace(tzinfo=None) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

        # Create Session in DB
        UserSessionRepository.create_session(
            db,
            user_id=user_id,
            refresh_token_hash=refresh_token_hash,
            expires_at=expires_at,
            user_agent=user_agent,
            ip_address=ip_address
        )

        create_audit_log(
            db,
            action="user_login",
            resource_type="user",
            resource_id=str(user_id),
            user_id=str(user_id),
            details={"ip": ip_address, "user_agent": user_agent}
        )

        return access_token, refresh_token_raw

    @staticmethod
    def rotate_session(
        db: Session,
        refresh_token_raw: str,
        user_agent: str | None = None,
        ip_address: str | None = None
    ) -> tuple[str, str]:
        token_hash = AuthService.hash_token(refresh_token_raw)
        session = UserSessionRepository.get_session_by_hash(db, token_hash)

        if not session:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token"
            )

        now = datetime.now(UTC).replace(tzinfo=None)

        # CONCURRENT-TAB GRACE: the refresh cookie is shared by every tab of a
        # browser, so two tabs refreshing together both present the same token.
        # The loser arrives just after the winner rotated it. Within a short
        # window, follow the replacement chain and rotate THAT session instead
        # of treating the replay as theft (the cookie jar ends up holding the
        # newest token either way).
        hops = 0
        while (
            session.is_revoked
            and session.replaced_by_session_id is not None
            and session.last_used_at is not None
            and (now - session.last_used_at).total_seconds() <= settings.REFRESH_GRACE_SECONDS
            and hops < 5
        ):
            replacement = UserSessionRepository.get_session_by_id(db, session.replaced_by_session_id)
            if replacement is None:
                break
            session = replacement
            hops += 1

        # REUSE DETECTION: if the session has already been revoked
        if session.is_revoked:
            # Revoke ALL active sessions for this user due to potential theft
            UserSessionRepository.revoke_all_sessions_for_user(db, session.user_id)
            db.commit()

            # Audit event log
            create_audit_log(
                db,
                action="token_reuse_detected",
                resource_type="user_session",
                resource_id=str(session.id),
                user_id=str(session.user_id),
                details={
                    "ip": ip_address,
                    "user_agent": user_agent,
                    "revoked_session_id": str(session.id)
                }
            )

            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Security alert: Token reuse detected. All sessions revoked."
            )

        # Expiration Check
        if session.expires_at <= now:
            session.is_revoked = True
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh token expired"
            )

        # Valid Session -> Rotate Token
        new_refresh_token_raw = secrets.token_urlsafe(64)
        new_refresh_token_hash = AuthService.hash_token(new_refresh_token_raw)
        new_expires_at = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

        # Create new session
        new_session = UserSessionRepository.create_session(
            db,
            user_id=session.user_id,
            refresh_token_hash=new_refresh_token_hash,
            expires_at=new_expires_at,
            user_agent=user_agent,
            ip_address=ip_address
        )

        # Link and mark old session as replaced and revoked
        session.is_revoked = True
        session.replaced_by_session_id = new_session.id
        session.last_used_at = now
        db.flush()

        # Generate new access token
        new_access_token = create_access_token(subject=str(session.user_id))

        create_audit_log(
            db,
            action="token_refreshed",
            resource_type="user_session",
            resource_id=str(new_session.id),
            user_id=str(session.user_id),
            details={"ip": ip_address, "user_agent": user_agent}
        )

        return new_access_token, new_refresh_token_raw

    @staticmethod
    def logout_session(db: Session, refresh_token_raw: str) -> None:
        token_hash = AuthService.hash_token(refresh_token_raw)
        session = UserSessionRepository.get_session_by_hash(db, token_hash)
        if session:
            session.is_revoked = True
            db.commit()
            create_audit_log(
                db,
                action="user_logout",
                resource_type="user_session",
                resource_id=str(session.id),
                user_id=str(session.user_id)
            )

    @staticmethod
    def logout_all_sessions(db: Session, user_id: uuid.UUID) -> None:
        UserSessionRepository.revoke_all_sessions_for_user(db, user_id)
        db.commit()
        create_audit_log(
            db,
            action="logout_all_devices",
            resource_type="user",
            resource_id=str(user_id),
            user_id=str(user_id)
        )

    @staticmethod
    def list_active_sessions(
        db: Session,
        user_id: uuid.UUID,
        current_token_raw: str | None = None
    ) -> list[dict]:
        sessions = UserSessionRepository.get_active_sessions_for_user(db, user_id)
        current_hash = AuthService.hash_token(current_token_raw) if current_token_raw else None

        results = []
        for s in sessions:
            results.append({
                "session_id": str(s.id),
                "created_at": s.created_at.isoformat() + "Z" if s.created_at else None,
                "last_used_at": s.last_used_at.isoformat() + "Z" if s.last_used_at else None,
                "user_agent": s.user_agent or "Unknown Device",
                "ip_address": s.ip_address or "Unknown IP",
                "is_current": s.refresh_token_hash == current_hash if current_hash else False
            })
        return results
