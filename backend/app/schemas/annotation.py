"""Request / response schemas for the annotation workspaces (SPEC2 section 5.3).

The annotation ``data`` blob (and the derived ``majority`` / ``agreement`` /
``record`` blobs) are passed through as ``dict[str, Any]``; their shape is
documented in ``app.services.consensus`` and validated there, not here.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.queue import QueueResponse

AnnotationStatus = Literal["draft", "submitted", "returned"]
MyStatus = Literal["not_started", "draft", "submitted", "returned"]


# ─── Production workspace ────────────────────────────────────────────────────

class WorkspaceTaskListItem(BaseModel):
    id: str
    sequence: int = 0
    dataset: str = ""
    preview: str = ""
    status: str = "pending"
    submitted_count: int = 0
    required_annotators: int = 3
    my_status: MyStatus = "not_started"


class WorkspaceQueueResponse(BaseModel):
    queue: QueueResponse
    tasks: list[WorkspaceTaskListItem] = Field(default_factory=list)
    my_done: int = 0


class WorkspaceTask(BaseModel):
    """The task block shared by the production and QA task detail payloads."""
    id: str
    queue_id: str
    queue_name: str = ""
    sequence: int = 0
    dataset: str = ""
    input_text: str = ""
    data_length_chars: int = 0
    data_length_bucket: str = ""
    meta_data: dict[str, Any] = Field(default_factory=dict)
    status: str = "pending"
    source: str = "real_user"
    submitted_count: int = 0
    required_annotators: int = 3
    qa_notes: str = ""
    # Present (non-null) once the task is finalised; also carried by the QA payload.
    finalized_by_name: str | None = None
    finalized_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class MyAnnotation(BaseModel):
    status: AnnotationStatus = "draft"
    data: dict[str, Any] = Field(default_factory=dict)
    elapsed_seconds: int = 0
    submitted_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class WorkspaceTaskDetail(BaseModel):
    task: WorkspaceTask
    my_annotation: MyAnnotation | None = None
    editable: bool = False
    # Only set by POST /workspace/tasks/{id}/submit.
    next_task_id: str | None = None


class DraftRequest(BaseModel):
    data: dict[str, Any] = Field(default_factory=dict)
    elapsed_seconds: int = Field(default=0, ge=0)


class SubmitRequest(BaseModel):
    data: dict[str, Any] = Field(default_factory=dict)
    elapsed_seconds: int = Field(default=0, ge=0)


# ─── QA workspace ────────────────────────────────────────────────────────────

class QATaskListItem(BaseModel):
    id: str
    sequence: int = 0
    dataset: str = ""
    preview: str = ""
    status: str = "submitted"
    consensus_reached: bool | None = None
    finalized_by_name: str | None = None
    finalized_at: datetime | None = None


class QASourceQueue(BaseModel):
    id: str
    name: str
    required_annotators: int = 3


class QAQueueResponse(BaseModel):
    queue: QueueResponse
    source_queue: QASourceQueue | None = None
    tasks: list[QATaskListItem] = Field(default_factory=list)


class QAAnnotationItem(BaseModel):
    slot: int
    user_id: str | None = None
    user_name: str | None = None
    submitted_at: datetime | None = None
    elapsed_seconds: int = 0
    data: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, bool] = Field(default_factory=dict)


class QATaskDetail(BaseModel):
    task: WorkspaceTask
    annotations: list[QAAnnotationItem] = Field(default_factory=list)
    majority: dict[str, Any] = Field(default_factory=dict)
    agreement: dict[str, str] = Field(default_factory=dict)
    consensus_reached: bool = False
    final: dict[str, Any] = Field(default_factory=dict)
    record: dict[str, Any] = Field(default_factory=dict)
    editable: bool = False
    # Only set by POST /workspace/qa/tasks/{id}/finalize.
    next_task_id: str | None = None


class PreviewRequest(BaseModel):
    data: dict[str, Any] = Field(default_factory=dict)


class PreviewResponse(BaseModel):
    record: dict[str, Any] = Field(default_factory=dict)


class FinalizeRequest(BaseModel):
    data: dict[str, Any] = Field(default_factory=dict)
    qa_notes: str = ""


class ReturnRequest(BaseModel):
    qa_notes: str = Field(min_length=3, max_length=4000)


class ReturnResponse(BaseModel):
    success: bool = True
    next_task_id: str | None = None
