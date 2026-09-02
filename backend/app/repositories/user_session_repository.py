import uuid
from datetime import datetime, UTC
from sqlalchemy.orm import Session
from app.models.user_session import UserSession

class UserSessionRepository:
    @staticmethod
    def create_session(
        db: Session,
        *,
        user_id: uuid.UUID,
        refresh_token_hash: str,
        expires_at: datetime,
        user_agent: str | None = None,
        ip_address: str | None = None
    ) -> UserSession:
        session = UserSession(
            user_id=user_id,
            refresh_token_hash=refresh_token_hash,
            expires_at=expires_at,
            user_agent=user_agent,
            ip_address=ip_address,
            is_revoked=False
        )
        db.add(session)
        db.flush()  # to populate session.id
        return session

    @staticmethod
    def get_session_by_hash(db: Session, refresh_token_hash: str) -> UserSession | None:
        return (
            db.query(UserSession)
            .filter(UserSession.refresh_token_hash == refresh_token_hash)
            .first()
        )

    @staticmethod
    def get_session_by_id(db: Session, session_id: uuid.UUID) -> UserSession | None:
        return db.query(UserSession).filter(UserSession.id == session_id).first()

    @staticmethod
    def revoke_session(db: Session, session_id: uuid.UUID) -> bool:
        session = db.query(UserSession).filter(UserSession.id == session_id).first()
        if session:
            session.is_revoked = True
            db.flush()
            return True
        return False

    @staticmethod
    def revoke_all_sessions_for_user(db: Session, user_id: uuid.UUID) -> bool:
        db.query(UserSession).filter(
            UserSession.user_id == user_id,
            UserSession.is_revoked == False
        ).update({"is_revoked": True}, synchronize_session=False)
        db.flush()
        return True

    @staticmethod
    def get_active_sessions_for_user(db: Session, user_id: uuid.UUID) -> list[UserSession]:
        now = datetime.now(UTC).replace(tzinfo=None)
        return (
            db.query(UserSession)
            .filter(
                UserSession.user_id == user_id,
                UserSession.is_revoked == False,
                UserSession.expires_at > now
            )
            .order_by(UserSession.created_at.desc())
            .all()
        )

    @staticmethod
    def cleanup_expired_sessions(db: Session) -> int:
        now = datetime.now(UTC).replace(tzinfo=None)
        deleted = db.query(UserSession).filter(
            (UserSession.expires_at <= now) | (UserSession.is_revoked == True)
        ).delete(synchronize_session=False)
        db.flush()
        return deleted
