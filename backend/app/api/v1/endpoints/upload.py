import os
import shutil
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse

from app.core.config import settings
from app.core.dependencies import get_current_user

router = APIRouter()

# Where uploads land. ``UPLOAD_FOLDER`` (settings / compose) is the documented
# knob; the older ``UPLOAD_DIR`` env var is still honoured. Point it at a
# shared volume when running more than one replica.
UPLOAD_DIR = os.environ.get("UPLOAD_DIR") or settings.UPLOAD_FOLDER or "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

ALLOWED_EXTENSIONS = {
    "image": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"},
    "video": {".mp4", ".avi", ".mov", ".wmv", ".mkv", ".webm"},
    "audio": {".mp3", ".wav", ".ogg", ".flac", ".aac"},
    "document": {
        ".pdf", ".doc", ".docx", ".txt", ".csv",
        ".json", ".jsonl", ".md", ".xlsx",
    },
}
ALL_ALLOWED = set().union(*ALLOWED_EXTENSIONS.values())
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB


@router.post("/")
def upload_file(
    _: Annotated[dict, Depends(get_current_user)],
    file: UploadFile = File(...),
) -> dict[str, str]:
    """Plain ``def``: the copy runs on the thread pool, never on the event loop,
    and the body is streamed to disk instead of being buffered in memory."""
    if not file.filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No file provided")

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALL_ALLOWED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File type {ext} not allowed",
        )

    # Size check without loading the file: SpooledTemporaryFile supports seek/tell.
    file.file.seek(0, os.SEEK_END)
    size = file.file.tell()
    file.file.seek(0)
    if size > MAX_FILE_SIZE:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="File too large (max 50MB)")

    unique_name = f"{uuid.uuid4().hex}{ext}"
    file_path = os.path.join(UPLOAD_DIR, unique_name)
    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f, length=1024 * 1024)

    file_url = f"/api/v1/upload/files/{unique_name}"
    return {"file_url": file_url, "file_name": file.filename, "file_type": ext.lstrip(".")}


@router.get("/files/{filename}")
def serve_file(filename: str) -> FileResponse:
    # No auth required — filenames are UUID-based; browsers cannot send Bearer tokens via <img src>
    # Strip any path components so an encoded ../ can never escape UPLOAD_DIR.
    safe_name = os.path.basename(filename.replace("\\", "/"))
    file_path = os.path.abspath(os.path.join(UPLOAD_DIR, safe_name))
    upload_root = os.path.abspath(UPLOAD_DIR)
    if not file_path.startswith(upload_root + os.sep):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid filename")
    if not os.path.exists(file_path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    return FileResponse(file_path)
