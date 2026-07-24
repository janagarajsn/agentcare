from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.db.models import WorkflowStatus
from app.schemas.appointment import AppointmentOut
from app.schemas.document import PatientDocumentOut
from app.schemas.escalation import EscalationOut
from app.schemas.reminder import ReminderOut


class WorkflowRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    patient_id: int
    current_step: str
    state: dict
    status: WorkflowStatus
    request_text: str
    created_at: datetime
    updated_at: datetime


class SubmitRequestResponse(BaseModel):
    """Every field here is populated from a persisted DB row looked up
    after the pipeline runs — never a fixed string."""

    workflow_run: WorkflowRunOut
    appointment: AppointmentOut | None = None
    documents: list[PatientDocumentOut] = []
    reminders: list[ReminderOut] = []
    escalation: EscalationOut | None = None
