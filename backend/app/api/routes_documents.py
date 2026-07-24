from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.auth.rbac import get_current_patient_profile, get_current_user
from app.db.models import DocumentType, PatientProfile, User, UserRole
from app.db.session import get_db
from app.schemas.document import MissingDocumentsResponse, PatientDocumentOut
from app.services.appointment_service import AppointmentNotFoundError, get_appointment
from app.services.document_service import DocumentNotFoundError, get_document, list_patient_documents
from app.tools.document_tool import classify_and_store_document, find_missing_documents

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/upload", response_model=PatientDocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_document(
    document_type: DocumentType = Form(...),
    document_date: date | None = Form(default=None),
    appointment_id: int | None = Form(default=None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    patient: PatientProfile = Depends(get_current_patient_profile),
):
    content = await file.read()
    result = classify_and_store_document(
        db,
        patient,
        content=content,
        content_type=file.content_type or "application/octet-stream",
        original_filename=file.filename or "upload",
        document_type=document_type,
        document_date=document_date,
        appointment_id=appointment_id,
    )
    if result["status"] != "stored":
        code = (
            status.HTTP_404_NOT_FOUND
            if result["status"] == "appointment_not_found"
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=code, detail=result["detail"])

    return get_document(db, result["document_id"])


@router.get("", response_model=list[PatientDocumentOut])
def list_my_documents(
    db: Session = Depends(get_db),
    patient: PatientProfile = Depends(get_current_patient_profile),
):
    return list_patient_documents(db, patient.id)


@router.get("/{document_id}", response_model=PatientDocumentOut)
def get_one_document(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        document = get_document(db, document_id)
    except DocumentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    if current_user.role == UserRole.PATIENT:
        profile = get_current_patient_profile(current_user=current_user, db=db)
        if document.patient_id != profile.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your document")

    return document


@router.get("/appointment/{appointment_id}/missing", response_model=MissingDocumentsResponse)
def missing_documents_for_appointment(
    appointment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        appointment = get_appointment(db, appointment_id)
    except AppointmentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    if current_user.role == UserRole.PATIENT:
        profile = get_current_patient_profile(current_user=current_user, db=db)
        if appointment.patient_id != profile.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your appointment")

    result = find_missing_documents(db, appointment_id)
    if result["status"] != "ok":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=result["detail"])
    return {"appointment_id": appointment_id, **{k: v for k, v in result.items() if k != "status"}}
