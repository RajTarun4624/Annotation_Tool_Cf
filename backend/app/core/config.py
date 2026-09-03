from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
    )

    APP_NAME: str = "Prompt Attack Annotation Platform API"
    API_V1_STR: str = "/api/v1"
    SECRET_KEY: str = "CHANGE_ME_TO_A_LONG_RANDOM_VALUE"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    # Mark the refresh-token cookie Secure. Must be False when served over plain
    # HTTP (e.g. http://localhost:8005) or browsers drop the cookie; set to
    # True via env in any HTTPS deployment.
    COOKIE_SECURE: bool = False

    # PostgreSQL Database settings
    DB_USER: str = "postgres"
    DB_PASS: str = "1234"
    DB_HOST: str = "127.0.0.1"
    DB_PORT: int = 5432
    DB_NAME: str = "annotation_tool_promptattack"
    # Maintenance database used to connect *before* the app database exists so
    # `ensure_database()` can issue CREATE DATABASE for DB_NAME.
    MAINTENANCE_DB: str = "postgres"

    # Connection pool (per uvicorn worker). Sized so the worker's request
    # threadpool can't exhaust the pool and stall requests behind 30s pool
    # timeouts. Tune via env if max_connections is tight:
    # total ≈ workers × (DB_POOL_SIZE + DB_MAX_OVERFLOW).
    DB_POOL_SIZE: int = 15
    DB_MAX_OVERFLOW: int = 25
    DB_POOL_TIMEOUT: int = 10

    # Task claim lease (seconds). The workspace heartbeats every ~60 s while a
    # task is open; a claim (production draft or QA ownership) whose last
    # heartbeat is older than this no longer blocks other users. This is the
    # SageMaker Ground Truth "task lease" idea: an abandoned tab frees itself.
    CLAIM_LEASE_SECONDS: int = 600
    # A refresh token presented again within this many seconds of its rotation
    # is treated as a concurrent tab, not as theft (both tabs share one cookie).
    REFRESH_GRACE_SECONDS: int = 30
    # Postgres advisory lock key serialising startup schema/seed work across
    # workers so `--workers N` (or several replicas) can boot safely.
    STARTUP_LOCK_KEY: int = 727272001
    # Per-process cache of the authenticated user (id -> profile/permissions).
    USER_CACHE_SECONDS: int = 15
    # Dashboard aggregates (counts over the whole task table) cache.
    DASHBOARD_CACHE_SECONDS: int = 30
    # Sync endpoints run on this many threads per worker. 0 = pool_size +
    # max_overflow, so a request never blocks on a connection checkout.
    THREADPOOL_TOKENS: int = 0

    CORS_ORIGINS: str = "http://localhost:8005,http://127.0.0.1:8005,http://localhost:3000,http://127.0.0.1:3000"
    CORS_ORIGIN_REGEX: str = r"^https?://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+)(:\d+)?$"

    DEFAULT_ADMIN_EMAIL: str = "admin@example.com"
    DEFAULT_ADMIN_PASSWORD: str = "Admin@123"

    UPLOAD_FOLDER: str = "app/uploads"

    # Plain-HTML frontend served by FastAPI at "/" (same origin as the API).
    # Relative to the backend working directory; resolved with os.path.abspath
    # in app/main.py. Set to a non-existent path to disable static serving.
    FRONTEND_DIR: str = "../frontend"

    @property
    def sqlalchemy_database_uri(self) -> str:
        return f"postgresql://{self.DB_USER}:{self.DB_PASS}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]


settings = Settings()
