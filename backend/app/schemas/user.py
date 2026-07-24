from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from app.db.models import UserRole


class PatientProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    date_of_birth: date | None
    phone: str | None
    preferred_language: str
    emergency_contact: str | None
    created_at: datetime
    updated_at: datetime


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    role: UserRole
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None
    patient_profile: PatientProfileOut | None = None
