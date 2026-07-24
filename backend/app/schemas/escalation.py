from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import EscalationReason, EscalationStatus


class EscalationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    workflow_run_id: int
    reason: EscalationReason
    detail: str | None
    status: EscalationStatus
    reviewed_by: int | None
    review_note: str | None
    created_at: datetime
    resolved_at: datetime | None


class EscalationResolveRequest(BaseModel):
    decision: Literal["approved", "rejected"]
    note: str | None = Field(default=None, max_length=2000)
