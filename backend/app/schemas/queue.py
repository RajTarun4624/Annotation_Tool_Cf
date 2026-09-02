"""Queue + task request/response schemas for the Prompt Attack Annotation Platform.

Tasks are relational rows (see ``app.models.task.Task``); a queue response
carries aggregate task counters, never the task list itself. The task list is
served (paginated) by ``GET /queues/{id}/tasks``.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


AnnotationType = Literal["production", "qa"]
Priority = Literal["low", "medium", "high", "critical"]
# Global queue lifecycle: inactive (nobody assigned) → active (assigned) →
# completed. Per-user "in_progress"/"paused" are derived per requesting
# annotator (see QueueResponse.user_status), not stored.
QueueStatus = Literal["inactive", "active", "completed"]
TaskStatus = Literal[
    "pending", "active", "paused", "skipped", "submitted",
    "declined", "approved", "rejected", "returned",
]


# ─── Requests ───────────────────────────────────────────────────────────────

class QueueTaskInput(BaseModel):
    """One task seed supplied at queue creation.

    Prompt tasks (sheet import): ``dataset`` + ``input`` (+ ``meta_data`` seed
    values copied from the sheet). The legacy file fields stay optional so the
    older file-based create flow keeps working.
    """
    dataset: str = ""
    input: str = ""
    meta_data: dict[str, Any] = Field(default_factory=dict)
    file_url: str = ""
    file_name: str = ""
    file_type: str = ""
    batch_name: str = ""
    annotation_data: dict[str, Any] = Field(default_factory=dict)


class QueueCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    project_id: str
    task_name: str = ""
    batch_name: str = ""
    annotation_type: AnnotationType = "production"
    priority: Priority = "medium"
    sla_hours: int = Field(default=24, ge=1, le=720)
    # Per-task timer in seconds: 1 min to 90000 min.
    timer_seconds: int = Field(default=7200, ge=60, le=5_400_000)
    # How many annotators must submit each task before it moves to QA.
    required_annotators: int = Field(default=3, ge=1, le=5)
    # Up to 5000 prompt rows (enforced in crud.create_queue).
    tasks: list[QueueTaskInput] = Field(default_factory=list)


class QueueUpdateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    annotation_type: AnnotationType = "production"
    priority: Priority = "medium"
    sla_hours: int = Field(default=24, ge=1, le=720)
    status: QueueStatus = "inactive"


class QueueAssignRequest(BaseModel):
    user_id: str


class QueueAssigneesRequest(BaseModel):
    """Set-semantics multi-user assignment: the full list replaces the current
    assignee pool. An empty list unassigns the queue."""
    user_ids: list[str] = Field(default_factory=list)


# ─── Responses ──────────────────────────────────────────────────────────────

class TaskResponse(BaseModel):
    id: str
    queue_id: str
    file_url: str = ""
    file_name: str = ""
    file_type: str = ""
    batch_name: str = ""
    status: str = "pending"
    environment: str = "production"
    assigned_to: str | None = None
    assigned_to_name: str | None = None
    submitted_at: datetime | None = None
    started_at: datetime | None = None
    paused_at: datetime | None = None
    timer_seconds: int = 7200
    elapsed_seconds: int = 0
    declined_reason: str = ""
    qa_notes: str = ""
    submitted_by: str = ""
    annotation_version: int = 1
    # Prompt-attack fields (SPEC2 5.1).
    dataset: str = ""
    input_preview: str = ""          # first 140 chars of the prompt, single line
    sequence: int = 0
    submitted_count: int = 0
    required_annotators: int = 3
    finalized_by_name: str | None = None
    finalized_at: datetime | None = None
    # From final_record.inter_annotator_agreement when approved; None otherwise.
    consensus_reached: bool | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class QueueResponse(BaseModel):
    id: str
    name: str
    project_id: str
    project_name: str | None = None
    task_name: str = ""
    batch_name: str = ""
    annotation_type: str
    priority: str
    sla_hours: int
    status: str
    # Per-requesting-user display status for the annotator's "My queues" list:
    # in_progress / paused / active / completed. None for admin/global callers.
    user_status: str | None = None
    assigned_user_id: str | None = None
    assigned_user_name: str | None = None
    assigned_user_ids: list[str] = Field(default_factory=list)
    assigned_user_names: list[str] = Field(default_factory=list)
    linked_qa_queue_id: str | None = None
    source_production_queue_id: str | None = None
    # Annotators that must submit each task before it moves to QA.
    required_annotators: int = 3
    # Aggregate counters. Production queues count Task.queue_id == id by
    # status (submitted_tasks = awaiting QA, approved_tasks = finalised);
    # QA queues count Task.qa_queue_id == id (total = awaiting + approved).
    total_tasks: int = 0
    pending_tasks: int = 0
    active_tasks: int = 0
    submitted_tasks: int = 0
    approved_tasks: int = 0
    rejected_tasks: int = 0
    declined_tasks: int = 0
    skipped_tasks: int = 0
    returned_tasks: int = 0
    # Only meaningful with the assigned_user_id filter: production -> tasks the
    # user has a submitted annotation for; QA -> approved tasks in the queue.
    user_done_tasks: int = 0
    timer_seconds: int = 7200
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class QueueTasksSummary(BaseModel):
    queue_name: str
    queue_type: str
    total_tasks: int = 0
    completed_tasks: int = 0
    pending_tasks: int = 0
    submitted_to_qa: int = 0
    assigned_user: str | None = None
    progress_percent: int = 0
    status: str


class QueueTasksResponse(BaseModel):
    queue: QueueResponse
    summary: QueueTasksSummary
    tasks: list[TaskResponse] = Field(default_factory=list)
    pagination: dict[str, int] = Field(default_factory=lambda: {"total": 0, "page": 1, "page_size": 0})
