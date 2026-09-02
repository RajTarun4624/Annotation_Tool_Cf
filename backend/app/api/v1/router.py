from fastapi import APIRouter

from app.api.v1.endpoints import (
    annotation,
    auth,
    dashboard,
    features,
    projects,
    queues,
    roles,
    tasks,
    upload,
    users,
    workspace,
)

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(features.router, prefix="/features", tags=["features"])
api_router.include_router(roles.router, prefix="/roles", tags=["roles"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(projects.router, prefix="/projects", tags=["projects"])
api_router.include_router(queues.router, prefix="/queues", tags=["queues"])
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
api_router.include_router(upload.router, prefix="/upload", tags=["upload"])
api_router.include_router(tasks.router, prefix="/tasks", tags=["tasks"])
api_router.include_router(annotation.router, prefix="/annotation", tags=["annotation"])
api_router.include_router(workspace.router, prefix="/workspace", tags=["workspace"])
