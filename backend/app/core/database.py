import logging
from collections.abc import Generator

import psycopg2
from psycopg2 import errors as pg_errors
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.models.base import Base

# Use uvicorn's logger so bootstrap messages show up in the server output
# (uvicorn does not configure the root logger, so INFO on a module logger
# would be silently dropped).
logger = logging.getLogger("uvicorn.error")

# Pool sizing: uvicorn runs sync endpoints on a ~40-thread pool per worker, so
# the default SQLAlchemy pool (5 + 10 overflow) exhausts under load and threads
# stack up behind 30 s pool timeouts — which is how the API "freezes" while the
# process looks alive. Budget: workers × (pool_size + max_overflow) must stay
# under Postgres max_connections.
engine = create_engine(
    settings.sqlalchemy_database_uri,
    pool_pre_ping=True,   # recycle silently-dropped connections instead of 500ing
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_timeout=settings.DB_POOL_TIMEOUT,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ensure_database() -> None:
    """Create the application database if it does not exist yet.

    Connects with psycopg2 (autocommit — CREATE DATABASE cannot run inside a
    transaction) to the maintenance database (`settings.MAINTENANCE_DB`) using
    the same host/port/user/password, checks `pg_database`, and creates
    `settings.DB_NAME` when missing. Idempotent: an existing database (or a
    concurrent creation racing us) is treated as success.

    Any failure to reach the maintenance DB is logged as a warning and NOT
    raised — the real engine connection will fail loudly right after this in
    `ensure_indexes()` if the app database is genuinely unavailable.
    """
    db_name = settings.DB_NAME
    conn = None
    try:
        conn = psycopg2.connect(
            dbname=settings.MAINTENANCE_DB,
            user=settings.DB_USER,
            password=settings.DB_PASS,
            host=settings.DB_HOST,
            port=settings.DB_PORT,
            connect_timeout=5,
        )
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db_name,))
            if cur.fetchone():
                logger.info("Database %r already exists - skipping creation.", db_name)
                return
            # Identifier, not a value: quote it as an identifier (double quotes,
            # inner double quotes escaped) — %s placeholders are for literals only.
            quoted = '"' + db_name.replace('"', '""') + '"'
            try:
                cur.execute(f"CREATE DATABASE {quoted}")
                logger.info("Created database %r.", db_name)
            except pg_errors.DuplicateDatabase:
                # Another process created it between our check and CREATE.
                logger.info("Database %r already exists (created concurrently).", db_name)
    except Exception as exc:  # noqa: BLE001 — deliberately broad: never crash startup here
        logger.warning(
            "Could not verify/create database %r via maintenance DB %r at %s:%s: %s",
            db_name,
            settings.MAINTENANCE_DB,
            settings.DB_HOST,
            settings.DB_PORT,
            exc,
        )
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass


def ensure_indexes() -> None:
    # Base.metadata.create_all creates every table and index defined on the
    # models that does not exist yet (no-op for existing ones).
    Base.metadata.create_all(bind=engine)
    # Schema tweaks create_all cannot express (mirrors alembic 0005): several
    # responses per annotator per task, each output row linked to its response.
    with engine.begin() as conn:
        conn.exec_driver_sql("ALTER TABLE task_annotations DROP CONSTRAINT IF EXISTS uq_task_annotations_task_user")
        conn.exec_driver_sql("ALTER TABLE tasks_output DROP CONSTRAINT IF EXISTS uq_tasks_output_task_user")
        conn.exec_driver_sql("ALTER TABLE tasks_output ADD COLUMN IF NOT EXISTS annotation_id UUID NULL")
        conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_tasks_output_annotation_id ON tasks_output (annotation_id)")
