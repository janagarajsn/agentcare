import hashlib
import uuid
from datetime import date

from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import Appointment, DocumentType, PatientDocument, PatientProfile
from app.tools.audit_tool import record_audit_event

ALLOWED_CONTENT_TYPES = {
    "application/pdf": ".pdf",
    "image/png": ".png",
    "image/jpeg": ".jpg",
}

REQUIRED_DOCUMENTS_BY_DEPARTMENT: dict[str, list[DocumentType]] = {
    "Cardiology": [DocumentType.ECG, DocumentType.BLOOD_REPORT],
    "Orthopedics": [DocumentType.IMAGING],
}

_FILENAME_TYPE_KEYWORDS: list[tuple[str, DocumentType]] = [
    ("ecg", DocumentType.ECG),
    ("ekg", DocumentType.ECG),
    ("blood", DocumentType.BLOOD_REPORT),
    ("cbc", DocumentType.BLOOD_REPORT),
    ("xray", DocumentType.IMAGING),
    ("x-ray", DocumentType.IMAGING),
    ("mri", DocumentType.IMAGING),
    ("scan", DocumentType.IMAGING),
    ("ct", DocumentType.IMAGING),
    ("discharge", DocumentType.DISCHARGE_SUMMARY),
    ("prescription", DocumentType.PRESCRIPTION_HISTORY),
    ("rx", DocumentType.PRESCRIPTION_HISTORY),
    ("insurance", DocumentType.INSURANCE_CARD),
    ("passport", DocumentType.IDENTITY_PROOF),
    ("license", DocumentType.IDENTITY_PROOF),
    ("referral", DocumentType.REFERRAL_LETTER),
]


def classify_by_filename(filename: str) -> DocumentType:
    """Deterministic filename-keyword classifier used when a document type
    isn't explicitly provided (the agent-driven upload path)."""
    lowered = filename.lower()
    for keyword, doc_type in _FILENAME_TYPE_KEYWORDS:
        if keyword in lowered:
            return doc_type
    return DocumentType.OTHER


class UnsupportedFileTypeError(Exception):
    pass


class FileTooLargeError(Exception):
    pass


class DocumentNotFoundError(Exception):
    pass


class AppointmentNotFoundForDocumentError(Exception):
    pass


def compute_checksum(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def store_document(
    db: Session,
    patient: PatientProfile,
    *,
    content: bytes,
    content_type: str,
    original_filename: str,
    document_type: DocumentType,
    document_date: date | None,
    appointment_id: int | None,
) -> PatientDocument:
    settings = get_settings()

    if content_type not in ALLOWED_CONTENT_TYPES:
        raise UnsupportedFileTypeError(
            f"Content type '{content_type}' is not allowed; supported types: {sorted(ALLOWED_CONTENT_TYPES)}"
        )

    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise FileTooLargeError(f"File exceeds the {settings.max_upload_size_mb}MB upload limit")

    if appointment_id is not None:
        appointment = db.get(Appointment, appointment_id)
        if appointment is None or appointment.patient_id != patient.id:
            raise AppointmentNotFoundForDocumentError(
                f"Appointment {appointment_id} not found for this patient"
            )

    checksum = compute_checksum(content)
    is_duplicate = (
        db.query(PatientDocument)
        .filter_by(patient_id=patient.id, checksum=checksum, document_type=document_type)
        .first()
        is not None
    )

    patient_dir = settings.document_storage_path / str(patient.id)
    patient_dir.mkdir(parents=True, exist_ok=True)
    extension = ALLOWED_CONTENT_TYPES[content_type]
    stored_filename = f"{uuid.uuid4().hex}{extension}"
    stored_path = patient_dir / stored_filename
    stored_path.write_bytes(content)

    document = PatientDocument(
        patient_id=patient.id,
        appointment_id=appointment_id,
        document_type=document_type,
        original_filename=original_filename,
        file_path=str(stored_path),
        document_date=document_date,
        checksum=checksum,
        is_duplicate=is_duplicate,
    )
    db.add(document)
    db.flush()

    record_audit_event(
        db,
        actor_id=patient.user_id,
        actor_role="patient",
        action="document_uploaded",
        entity_type="PatientDocument",
        entity_id=document.id,
        metadata={
            "document_type": document_type.value,
            "is_duplicate": is_duplicate,
            "appointment_id": appointment_id,
        },
    )
    db.commit()
    db.refresh(document)
    return document


def get_document(db: Session, document_id: int) -> PatientDocument:
    document = db.get(PatientDocument, document_id)
    if document is None:
        raise DocumentNotFoundError(f"Document {document_id} not found")
    return document


def list_patient_documents(db: Session, patient_id: int) -> list[PatientDocument]:
    return (
        db.query(PatientDocument)
        .filter_by(patient_id=patient_id)
        .order_by(PatientDocument.created_at.desc())
        .all()
    )


def check_missing_documents(db: Session, appointment_id: int) -> dict:
    appointment = db.get(Appointment, appointment_id)
    if appointment is None:
        raise AppointmentNotFoundForDocumentError(f"Appointment {appointment_id} not found")

    department = appointment.doctor.department
    required = REQUIRED_DOCUMENTS_BY_DEPARTMENT.get(department.name, [])

    uploaded_types = {
        doc.document_type
        for doc in db.query(PatientDocument).filter_by(appointment_id=appointment_id).all()
    }
    missing = [doc_type for doc_type in required if doc_type not in uploaded_types]

    return {
        "appointment_id": appointment_id,
        "department_name": department.name,
        "required": required,
        "uploaded": sorted(uploaded_types, key=lambda t: t.value),
        "missing": missing,
    }


def check_missing_documents_by_department(db: Session, patient_id: int, department_name: str) -> dict:
    """Department-scoped variant used by the agent pipeline, where document
    coordination happens before any appointment necessarily exists yet —
    checks against all of the patient's uploaded documents regardless of
    appointment link."""
    required = REQUIRED_DOCUMENTS_BY_DEPARTMENT.get(department_name, [])

    uploaded_types = {
        doc.document_type for doc in db.query(PatientDocument).filter_by(patient_id=patient_id).all()
    }
    missing = [doc_type for doc_type in required if doc_type not in uploaded_types]

    return {
        "department_name": department_name,
        "required": required,
        "uploaded": sorted(uploaded_types, key=lambda t: t.value),
        "missing": missing,
    }
