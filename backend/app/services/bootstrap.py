from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.security import get_password_hash
from app.models.user import DEFAULT_FEATURES, Feature, Role, User


def seed_default_admin() -> None:
    """Idempotent startup seed.

    1. Upserts every entry of DEFAULT_FEATURES into `features` (name,
       description, icon, order are refreshed on each boot so renames land).
    2. Upserts the "Administrator" role with ALL feature keys as permissions.
    3. Upserts the default admin user (DEFAULT_ADMIN_EMAIL / _PASSWORD) bound
       to that role. The password is reset to the configured value on every
       boot so a lost admin password is recoverable via env.
    """
    db: Session = SessionLocal()
    try:
        now = datetime.now(UTC)

        # Seed Features
        for f in DEFAULT_FEATURES:
            feature = db.query(Feature).filter(Feature.key == f["key"]).first()
            if not feature:
                feature = Feature(key=f["key"])
                db.add(feature)

            feature.name = f["name"]
            feature.description = f["description"]
            feature.icon = f["icon"]
            feature.order = f["order"]

        db.commit()

        # Seed Admin Role (every feature key)
        admin_role_permissions = [feature["key"] for feature in DEFAULT_FEATURES]
        admin_role = db.query(Role).filter(Role.name == "Administrator").first()
        if not admin_role:
            admin_role = Role(name="Administrator")
            db.add(admin_role)

        admin_role.description = "Full platform access across all modules."
        admin_role.permissions = admin_role_permissions
        admin_role.is_active = True

        db.commit()
        db.refresh(admin_role)

        # Seed Default Admin User
        admin_email = settings.DEFAULT_ADMIN_EMAIL.lower()
        admin_user = db.query(User).filter(User.email == admin_email).first()
        if not admin_user:
            admin_user = User(
                full_name="System Admin",
                email=admin_email,
                hashed_password=get_password_hash(settings.DEFAULT_ADMIN_PASSWORD),
                role_id=admin_role.id,
                is_active=True,
                created_at=now,
                updated_at=now,
            )
            db.add(admin_user)
        else:
            admin_user.role_id = admin_role.id
            admin_user.hashed_password = get_password_hash(settings.DEFAULT_ADMIN_PASSWORD)
            admin_user.is_active = True
            admin_user.updated_at = now

        db.commit()
    finally:
        db.close()
