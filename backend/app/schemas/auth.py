from datetime import date

from pydantic import BaseModel, EmailStr, Field

from app.db.models import UserRole


class PatientRegisterRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    date_of_birth: date | None = None
    phone: str | None = Field(default=None, max_length=32)
    preferred_language: str = Field(default="en", max_length=32)
    emergency_contact: str | None = Field(default=None, max_length=255)


class StaffCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    role: UserRole = UserRole.STAFF

    def validated_role(self) -> UserRole:
        if self.role == UserRole.PATIENT:
            raise ValueError("role must be 'staff' or 'admin'")
        return self.role


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str
