"""Startup seed: create what is missing, never rewrite what an admin changed.

Runs on every process start (under the startup advisory lock), so it must be
safe to repeat and must not undo operator actions:

1. Features: upsert the catalogue (name/description/icon/order are code-owned).
2. Roles: create the 3 canonical roles if missing; rename legacy names. The
   Admin role is topped up with any NEW feature key so a new page is reachable
   after a deploy, but permissions an admin removed from QA/User stay removed.
   Custom roles created through the UI are left alone.
3. Default accounts: created only when absent. Passwords, roles and the
   active flag of existing accounts are never touched - a rotated admin
   password survives a restart.
"""

import logging
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.security import get_password_hash
from app.models.user import DEFAULT_FEATURES, Feature, Role, User

logger = logging.getLogger("uvicorn.error")


ROLE_CONFIGS = [
    {
        "name": "Admin",
        "legacy_names": ["Administrator"],
        "description": "Full platform access across all administrative, management, and workspace modules.",
        "permissions": None,  # every feature key
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


def _seed_features(db: Session) -> list[str]:
    keys: list[str] = []
    for f in DEFAULT_FEATURES:
        feature = db.query(Feature).filter(Feature.key == f["key"]).first()
        if not feature:
            feature = Feature(key=f["key"])
            db.add(feature)
        feature.name = f["name"]
        feature.description = f["description"]
        feature.icon = f["icon"]
        feature.order = f["order"]
        keys.append(f["key"])
    db.commit()
    return keys


def _seed_roles(db: Session, all_feature_keys: list[str]) -> dict[str, Role]:
    roles: dict[str, Role] = {}
    for cfg in ROLE_CONFIGS:
        wanted = all_feature_keys if cfg["permissions"] is None else list(cfg["permissions"])
        role = db.query(Role).filter(Role.name == cfg["name"]).first()
        if not role:
            for legacy in cfg["legacy_names"]:
                role = db.query(Role).filter(Role.name == legacy).first()
                if role:
                    role.name = cfg["name"]
                    break
        if not role:
            role = Role(name=cfg["name"], description=cfg["description"], permissions=wanted, is_active=True)
            db.add(role)
            logger.info("Seeded role %r.", cfg["name"])
        elif cfg["permissions"] is None:
            # Admin: add new feature keys, keep whatever else is there.
            current = list(role.permissions or [])
            missing = [k for k in wanted if k not in current]
            if missing:
                role.permissions = current + missing
        db.commit()
        db.refresh(role)
        roles[cfg["name"]] = role
    return roles


def _seed_users(db: Session, roles: dict[str, Role]) -> None:
    now = datetime.now(UTC)
    seed_users = [
        {"email": settings.DEFAULT_ADMIN_EMAIL.lower(), "full_name": "System Admin",
         "password": settings.DEFAULT_ADMIN_PASSWORD, "role": roles["Admin"]},
        {"email": "qa@gmail.com", "full_name": "QA Specialist", "password": "Qa@123", "role": roles["QA"]},
        {"email": "user@gmail.com", "full_name": "Annotation User", "password": "User@123", "role": roles["User"]},
    ]
    for cfg in seed_users:
        email = cfg["email"].lower()
        if db.query(User.id).filter(User.email == email).first():
            continue  # existing account: password / role / active flag are theirs to manage
        db.add(User(
            full_name=cfg["full_name"],
            email=email,
            hashed_password=get_password_hash(cfg["password"]),
            role_id=cfg["role"].id,
            is_active=True,
            created_at=now,
            updated_at=now,
        ))
        logger.info("Seeded default account %s.", email)
    db.commit()


def seed_default_admin() -> None:
    """Idempotent, non-destructive startup seed (see module docstring)."""
    db: Session = SessionLocal()
    try:
        keys = _seed_features(db)
        roles = _seed_roles(db, keys)
        _seed_users(db, roles)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
