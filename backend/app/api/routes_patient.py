from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.rbac import get_current_patient_profile
from app.db.models import PatientProfile
from app.db.session import get_db
from app.schemas.patient import PatientProfileUpdateRequest
from app.schemas.reminder import ReminderOut
from app.schemas.user import PatientProfileOut
from app.services.patient_service import update_patient_profile
from app.services.reminder_service import list_patient_reminders

router = APIRouter(prefix="/patients", tags=["patients"])


@router.get("/me", response_model=PatientProfileOut)
def get_my_profile(patient: PatientProfile = Depends(get_current_patient_profile)):
    return patient


@router.patch("/me", response_model=PatientProfileOut)
def update_my_profile(
    payload: PatientProfileUpdateRequest,
    db: Session = Depends(get_db),
    patient: PatientProfile = Depends(get_current_patient_profile),
):
    return update_patient_profile(db, patient, payload)


@router.get("/me/reminders", response_model=list[ReminderOut])
def get_my_reminders(
    db: Session = Depends(get_db),
    patient: PatientProfile = Depends(get_current_patient_profile),
):
    return list_patient_reminders(db, patient.id)
