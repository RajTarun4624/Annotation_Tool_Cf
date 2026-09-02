from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.security import get_password_hash
from app.models.user import DEFAULT_FEATURES, Feature, Role, User


def seed_default_admin() -> None:
    """Idempotent startup seed.

    1. Upserts every entry of DEFAULT_FEATURES into `features`.
    2. Upserts the 3 canonical roles: "Admin", "QA", and "User".
    3. Reassigns existing users from legacy roles and removes obsolete roles.
    4. Upserts default accounts:
       - admin@gmail.com / Admin@123 (Admin)
       - qa@gmail.com / Qa@123 (QA)
       - user@gmail.com / User@123 (User)
    """
    db: Session = SessionLocal()
    try:
        now = datetime.now(UTC)

        # 1. Seed Features
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

        # 2. Seed 3 Canonical Roles: Admin, QA, User
        all_feature_keys = [f["key"] for f in DEFAULT_FEATURES]

        role_configs = [
            {
                "name": "Admin",
                "legacy_names": ["Administrator"],
                "description": "Full platform access across all administrative, management, and workspace modules.",
                "permissions": all_feature_keys,
            },
            {
                "name": "QA",
                "legacy_names": ["QA Reviewer"],
                "description": "Quality assurance and review access for tasks and annotation queues.",
                "permissions": ["tasks", "annotation_queues", "profile"],
            },
            {
                "name": "User",
                "legacy_names": ["Annotator"],
                "description": "Standard user and annotator access for working on annotation queues.",
                "permissions": ["annotation_queues", "profile"],
            },
        ]

        canonical_roles: dict[str, Role] = {}
        for cfg in role_configs:
            # Find existing role by name or legacy name
            role = db.query(Role).filter(Role.name == cfg["name"]).first()
            if not role:
                for leg in cfg["legacy_names"]:
                    role = db.query(Role).filter(Role.name == leg).first()
                    if role:
                        role.name = cfg["name"]
                        break
            if not role:
                role = Role(name=cfg["name"])
                db.add(role)

            role.description = cfg["description"]
            role.permissions = cfg["permissions"]
            role.is_active = True
            db.commit()
            db.refresh(role)
            canonical_roles[cfg["name"]] = role

        admin_role = canonical_roles["Admin"]
        qa_role = canonical_roles["QA"]
        user_role = canonical_roles["User"]

        # 3. Clean up other leftover roles (reassigning any users to User role first)
        allowed_role_ids = {r.id for r in canonical_roles.values()}
        other_roles = db.query(Role).filter(~Role.id.in_(allowed_role_ids)).all()
        for r in other_roles:
            # Reassign any users to User role
            db.query(User).filter(User.role_id == r.id).update({"role_id": user_role.id})
            db.delete(r)
        db.commit()

        # 4. Clean up test users (flowtest.dev / test.com)
        from app.models.audit_log import AuditLog
        test_users = db.query(User).filter(
            User.email.like("%@flowtest.dev") | User.email.like("%@test.com")
        ).all()
        test_user_ids = [u.id for u in test_users]
        if test_user_ids:
            db.query(AuditLog).filter(AuditLog.user_id.in_(test_user_ids)).delete(synchronize_session=False)
            db.query(User).filter(User.id.in_(test_user_ids)).delete(synchronize_session=False)
            db.commit()


        # 5. Seed / Update 3 Default Users
        seed_users = [
            {
                "email": settings.DEFAULT_ADMIN_EMAIL.lower(),
                "full_name": "System Admin",
                "password": settings.DEFAULT_ADMIN_PASSWORD,
                "role": admin_role,
            },
            {
                "email": "qa@gmail.com",
                "full_name": "QA Specialist",
                "password": "Qa@123",
                "role": qa_role,
            },
            {
                "email": "user@gmail.com",
                "full_name": "Annotation User",
                "password": "User@123",
                "role": user_role,
            },
        ]

        for u_cfg in seed_users:
            u_email = u_cfg["email"].lower()
            user = db.query(User).filter(User.email == u_email).first()
            if not user:
                user = User(
                    full_name=u_cfg["full_name"],
                    email=u_email,
                    hashed_password=get_password_hash(u_cfg["password"]),
                    role_id=u_cfg["role"].id,
                    is_active=True,
                    created_at=now,
                    updated_at=now,
                )
                db.add(user)
            else:
                user.role_id = u_cfg["role"].id
                user.hashed_password = get_password_hash(u_cfg["password"])
                user.is_active = True
                user.updated_at = now

        db.commit()
    finally:
        db.close()

