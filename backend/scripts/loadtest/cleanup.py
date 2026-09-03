"""Remove everything the load-test seed created (queues LT-*, users @loadtest.local).

    .venv/Scripts/python.exe -m scripts.loadtest.cleanup [--keep-users]
"""

from __future__ import annotations

import argparse
import sys

sys.path.insert(0, ".")

from sqlalchemy import text  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from scripts.loadtest.common import TAG_PREFIX, USER_DOMAIN  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep-users", action="store_true")
    args = ap.parse_args()
    db = SessionLocal()
    try:
        n_qa = db.execute(text("DELETE FROM queues WHERE annotation_type = 'qa' AND name LIKE :p"), {"p": f"{TAG_PREFIX}%"}).rowcount
        n_prod = db.execute(text("DELETE FROM queues WHERE name LIKE :p"), {"p": f"{TAG_PREFIX}%"}).rowcount
        n_users = 0
        if not args.keep_users:
            db.execute(text("DELETE FROM audit_logs WHERE user_id IN (SELECT id FROM users WHERE email LIKE :d)"), {"d": f"%@{USER_DOMAIN}"})
            db.execute(text("DELETE FROM user_sessions WHERE user_id IN (SELECT id FROM users WHERE email LIKE :d)"), {"d": f"%@{USER_DOMAIN}"})
            n_users = db.execute(text("DELETE FROM users WHERE email LIKE :d"), {"d": f"%@{USER_DOMAIN}"}).rowcount
        db.commit()
        print(f"deleted {n_prod} production queues (+{n_qa} QA queues, tasks cascade) and {n_users} users")
    finally:
        db.close()


if __name__ == "__main__":
    main()
