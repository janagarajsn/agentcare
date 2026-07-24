from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import AppointmentStatus, SlotStatus


class SlotCreateRequest(BaseModel):
    doctor_id: int
    start_time: datetime
    end_time: datetime


class SlotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    doctor_id: int
    start_time: datetime
    end_time: datetime
    status: SlotStatus


class AppointmentCreateRequest(BaseModel):
    slot_id: int
    reason: str | None = Field(default=None, max_length=2000)


class RescheduleRequest(BaseModel):
    new_slot_id: int


class AppointmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    patient_id: int
    doctor_id: int
    doctor_name: str
    department_name: str
    slot_id: int
    slot_start_time: datetime
    slot_end_time: datetime
    status: AppointmentStatus
    reason: str | None
    created_at: datetime
    updated_at: datetime
