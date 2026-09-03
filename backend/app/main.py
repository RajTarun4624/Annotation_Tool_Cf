import logging
import os
from contextlib import asynccontextmanager

import anyio
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.database import ensure_database, ensure_indexes, startup_lock
from app.core.errors import ConflictError
from app.services.bootstrap import seed_default_admin

logger = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Sync endpoints run on anyio's thread pool. Size it to the DB pool so a
    # request queues for a thread (cheap) instead of a connection (10 s timeout).
    tokens = settings.THREADPOOL_TOKENS or (settings.DB_POOL_SIZE + settings.DB_MAX_OVERFLOW)
    anyio.to_thread.current_default_thread_limiter().total_tokens = max(8, int(tokens))
    # Order matters: the app DB must exist before create_all can run against
    # it, and tables must exist before the admin/feature seed writes rows.
    ensure_database()
    # One process at a time: several workers/replicas booting together must not
    # race on DDL locks or read-then-insert seeds.
    with startup_lock():
        ensure_indexes()
        seed_default_admin()
    if settings.SECRET_KEY == "CHANGE_ME_TO_A_LONG_RANDOM_VALUE":
        logger.warning(
            "SECRET_KEY is the insecure default — tokens are forgeable. "
            "Set SECRET_KEY in the environment before serving real users."
        )
    if settings.DEFAULT_ADMIN_PASSWORD == "Admin@123":
        logger.warning(
            "DEFAULT_ADMIN_PASSWORD is the well-known default — change it "
            "(or set the env var) in any shared deployment."
        )
    yield


app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_origin_regex=settings.CORS_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.API_V1_STR)


@app.exception_handler(ConflictError)
async def _conflict_handler(request: Request, exc: ConflictError) -> JSONResponse:
    """A row-locked re-check failed: someone else got there first. The client
    shows the message and asks for its next task."""
    return JSONResponse(status_code=409, content={"detail": exc.detail, "conflict": True})


@app.get("/health", tags=["health"])
async def health_check() -> dict[str, str]:
    # async: answers from the event loop even when every worker thread is busy.
    return {"status": "ok"}


_IMMUTABLE_EXT = (".js", ".css", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".woff", ".woff2")


class CacheControlStatic:
    """Pure-ASGI wrapper around StaticFiles (no BaseHTTPMiddleware task-group
    hop per request). HTML is always revalidated; versioned assets
    (``?v=...``) are cached for a year, matching the nginx edge config."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope.get("path", "") or ""
        versioned = path.lower().endswith(_IMMUTABLE_EXT) and b"v=" in (scope.get("query_string") or b"")
        value = b"public, max-age=31536000, immutable" if versioned else b"no-cache, must-revalidate"

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = [(k, v) for k, v in message.get("headers", []) if k.lower() != b"cache-control"]
                headers.append((b"cache-control", value))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_wrapper)


# Serve the plain-HTML frontend from the same origin as the API. Mounted LAST
# so every API route and /health registered above keeps precedence over the
# catch-all static mount. Skipped silently when the directory is absent (e.g.
# API-only deployments where nginx serves the frontend).
frontend_dir = os.path.abspath(settings.FRONTEND_DIR)
if os.path.isdir(frontend_dir):
    app.mount("/", CacheControlStatic(StaticFiles(directory=frontend_dir, html=True)), name="frontend")
    logger.info("Serving frontend from %s", frontend_dir)
else:
    logger.warning("FRONTEND_DIR %s not found - static frontend not mounted.", frontend_dir)
