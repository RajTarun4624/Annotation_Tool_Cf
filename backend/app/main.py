import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager

import anyio
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.database import engine, ensure_database, ensure_indexes, startup_lock
from app.core.errors import ConflictError
from app.core.observability import RequestTiming, install_slow_query_log, snapshot
from app.services.bootstrap import seed_default_admin

logger = logging.getLogger("uvicorn.error")


def request_concurrency_limit() -> int:
    if settings.REQUEST_CONCURRENCY:
        return max(2, int(settings.REQUEST_CONCURRENCY))
    return max(4, settings.DB_POOL_SIZE + settings.DB_MAX_OVERFLOW - 2)


class AdmissionControl:
    """Pure-ASGI admission control for API requests.

    Why: a request holds its DB connection from the first query until the
    session is closed, but FastAPI hops through the thread pool several times
    per request (dependencies, endpoint, teardown). Under a burst, requests
    waiting for a thread keep their connections, the pool empties, and every
    checkout times out (10 s) - a collapse, not a slowdown. Capping in-flight
    requests to the pool capacity makes excess requests wait in the event loop
    holding nothing; the queue is bounded and times out with a fast 503.
    """

    instances: list["AdmissionControl"] = []  # for /health/details

    def __init__(self, app, limit: int, max_queue: int, queue_timeout: float) -> None:
        self.app = app
        self.limit = limit
        self.max_queue = max_queue
        self.queue_timeout = queue_timeout
        self._sem: asyncio.Semaphore | None = None
        self.waiting = 0
        self.rejected = 0
        self.admitted = 0
        AdmissionControl.instances.append(self)

    def stats(self) -> dict:
        sem = self._sem
        in_flight = (self.limit - sem._value) if sem is not None else 0  # noqa: SLF001
        return {
            "limit": self.limit, "in_flight": max(0, in_flight), "waiting": self.waiting,
            "admitted": self.admitted, "rejected_503": self.rejected,
            "queue_max": self.max_queue, "queue_timeout_s": self.queue_timeout,
        }

    def _semaphore(self) -> asyncio.Semaphore:
        if self._sem is None:
            self._sem = asyncio.Semaphore(self.limit)
        return self._sem

    async def _busy(self, send) -> None:
        self.rejected += 1
        body = b'{"detail":"The server is busy. Please retry in a moment."}'
        await send({
            "type": "http.response.start",
            "status": 503,
            "headers": [(b"content-type", b"application/json"), (b"retry-after", b"2"),
                        (b"content-length", str(len(body)).encode())],
        })
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not (scope.get("path") or "").startswith(settings.API_V1_STR):
            return await self.app(scope, receive, send)
        sem = self._semaphore()
        if self.waiting >= self.max_queue:
            return await self._busy(send)
        self.waiting += 1
        try:
            try:
                await asyncio.wait_for(sem.acquire(), timeout=self.queue_timeout)
            except asyncio.TimeoutError:
                return await self._busy(send)
        finally:
            self.waiting -= 1
        self.admitted += 1
        try:
            await self.app(scope, receive, send)
        finally:
            sem.release()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Sync endpoints run on anyio's thread pool. Admission control (below)
    # already bounds in-flight requests to the DB pool; give the thread pool a
    # little more so an admitted request never blocks on a thread while it
    # holds a connection.
    tokens = settings.THREADPOOL_TOKENS or (request_concurrency_limit() + 8)
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
    logger.info(
        "worker pid=%s ready: admission limit=%s, thread tokens=%s, db pool=%s+%s, "
        "lease=%ss, slow request/query thresholds=%s/%s ms",
        os.getpid(), request_concurrency_limit(), int(tokens), settings.DB_POOL_SIZE,
        settings.DB_MAX_OVERFLOW, settings.CLAIM_LEASE_SECONDS, settings.SLOW_REQUEST_MS,
        settings.SLOW_QUERY_MS,
    )
    yield
    engine.dispose()


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
# Bound in-flight API requests per worker (see AdmissionControl).
app.add_middleware(
    AdmissionControl,
    limit=request_concurrency_limit(),
    max_queue=settings.REQUEST_QUEUE_MAX,
    queue_timeout=settings.REQUEST_QUEUE_TIMEOUT,
)
# Outermost: request id + response-time header, slow/5xx log, counters. It
# wraps admission control so the measured time includes any queueing.
app.add_middleware(RequestTiming)
install_slow_query_log(engine)

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


def _db_ping() -> float:
    started = time.perf_counter()
    with engine.connect() as conn:
        conn.exec_driver_sql("SELECT 1").scalar()
    return round((time.perf_counter() - started) * 1000, 1)


@app.get("/health/details", tags=["health"])
async def health_details() -> JSONResponse:
    """Operational snapshot of THIS worker process: request counters, DB pool
    occupancy, admission-control queue, thread pool, and a live DB ping.
    Poll it from monitoring; `status` is "degraded" when the DB ping fails."""
    admission = AdmissionControl.instances[0].stats() if AdmissionControl.instances else None
    tokens = anyio.to_thread.current_default_thread_limiter().total_tokens
    body = snapshot(engine, admission, int(tokens))
    body["version"] = app.version
    try:
        body["db_ping_ms"] = await asyncio.wait_for(anyio.to_thread.run_sync(_db_ping), timeout=5)
        body["status"] = "ok"
        code = 200
    except Exception as exc:  # noqa: BLE001
        body["db_ping_ms"] = None
        body["db_error"] = str(exc)[:200]
        body["status"] = "degraded"
        code = 503
    return JSONResponse(status_code=code, content=body)


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
