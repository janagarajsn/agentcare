from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from app.db.models import DocumentType


class PatientDocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    patient_id: int
    appointment_id: int | None
    document_type: DocumentType
    original_filename: str
    document_date: date | None
    checksum: str
    is_duplicate: bool
    created_at: datetime


class MissingDocumentsResponse(BaseModel):
    appointment_id: int
    department_name: str
    required: list[DocumentType]
    uploaded: list[DocumentType]
    missing: list[DocumentType]
