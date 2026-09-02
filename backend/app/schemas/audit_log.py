from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AuditLogResponse(BaseModel):
    id: str
    user_id: str
    user_name: str
    action: str
    entity_type: str
    entity_id: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime

    model_config = {"from_attributes": True}
