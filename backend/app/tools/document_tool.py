from datetime import date

from sqlalchemy.orm import Session

from app.db.models import DocumentType, PatientProfile
from app.services.document_service import (
    AppointmentNotFoundForDocumentError,
    FileTooLargeError,
    UnsupportedFileTypeError,
    check_missing_documents,
    check_missing_documents_by_department,
    store_document,
)


def classify_and_store_document(
    db: Session,
    patient: PatientProfile,
    *,
    content: bytes,
    content_type: str,
    original_filename: str,
    document_type: DocumentType,
    document_date: date | None,
    appointment_id: int | None,
) -> dict:
    try:
        document = store_document(
            db,
            patient,
            content=content,
            content_type=content_type,
            original_filename=original_filename,
            document_type=document_type,
            document_date=document_date,
            appointment_id=appointment_id,
        )
    except UnsupportedFileTypeError as exc:
        return {"status": "unsupported_type", "detail": str(exc)}
    except FileTooLargeError as exc:
        return {"status": "too_large", "detail": str(exc)}
    except AppointmentNotFoundForDocumentError as exc:
        return {"status": "appointment_not_found", "detail": str(exc)}

    return {
        "status": "stored",
        "document_id": document.id,
        "document_type": document.document_type.value,
        "is_duplicate": document.is_duplicate,
        "checksum": document.checksum,
    }


def find_missing_documents(db: Session, appointment_id: int) -> dict:
    try:
        result = check_missing_documents(db, appointment_id)
    except AppointmentNotFoundForDocumentError as exc:
        return {"status": "appointment_not_found", "detail": str(exc)}

    return {
        "status": "ok",
        "department_name": result["department_name"],
        "required": [t.value for t in result["required"]],
        "uploaded": [t.value for t in result["uploaded"]],
        "missing": [t.value for t in result["missing"]],
    }


def find_missing_documents_by_department(db: Session, patient_id: int, department_name: str) -> dict:
    result = check_missing_documents_by_department(db, patient_id, department_name)
    return {
        "status": "ok",
        "department_name": result["department_name"],
        "required": [t.value for t in result["required"]],
        "uploaded": [t.value for t in result["uploaded"]],
        "missing": [t.value for t in result["missing"]],
    }
