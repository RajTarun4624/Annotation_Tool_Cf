import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.database import ensure_database, ensure_indexes
from app.services.bootstrap import seed_default_admin

logger = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Order matters: the app DB must exist before create_all can run against
    # it, and tables must exist before the admin/feature seed writes rows.
    ensure_database()
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


@app.middleware("http")
async def static_no_cache(request, call_next):
    """Frontend files are served same-origin without a build step, so make
    browsers revalidate them on every load (ETag/Last-Modified still allow
    cheap 304s). API responses are left untouched."""
    response = await call_next(request)
    path = request.url.path
    if not path.startswith(settings.API_V1_STR) and path != "/health":
        response.headers.setdefault("Cache-Control", "no-cache, must-revalidate")
    return response


@app.get("/health", tags=["health"])
def health_check() -> dict[str, str]:
    return {"status": "ok"}


# Serve the plain-HTML frontend from the same origin as the API. Mounted LAST
# so every API route and /health registered above keeps precedence over the
# catch-all static mount. Skipped silently when the directory is absent (e.g.
# API-only deployments where nginx serves the frontend).
frontend_dir = os.path.abspath(settings.FRONTEND_DIR)
if os.path.isdir(frontend_dir):
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
    logger.info("Serving frontend from %s", frontend_dir)
else:
    logger.warning("FRONTEND_DIR %s not found - static frontend not mounted.", frontend_dir)
