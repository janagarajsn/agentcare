from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.db.models import ReminderStatus, ReminderType


class ReminderCreateRequest(BaseModel):
    reminder_type: ReminderType
    scheduled_at: datetime


class ReminderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    patient_id: int
    appointment_id: int | None
    workflow_run_id: int | None
    reminder_type: ReminderType
    scheduled_at: datetime
    status: ReminderStatus
    created_at: datetime


class NotificationLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    reminder_id: int
    channel: str
    message: str
    sent_at: datetime
