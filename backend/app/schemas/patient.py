from datetime import date

from pydantic import BaseModel, Field


class PatientProfileUpdateRequest(BaseModel):
    date_of_birth: date | None = None
    phone: str | None = Field(default=None, max_length=32)
    preferred_language: str | None = Field(default=None, max_length=32)
    emergency_contact: str | None = Field(default=None, max_length=255)
