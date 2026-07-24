from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth.rbac import get_current_patient_profile, get_current_user, require_role
from app.db.models import NotificationLog, PatientProfile, User, UserRole
from app.db.session import get_db
from app.schemas.appointment import AppointmentCreateRequest, AppointmentOut, RescheduleRequest
from app.schemas.department import DepartmentOut
from app.schemas.reminder import NotificationLogOut, ReminderCreateRequest, ReminderOut
from app.services.appointment_service import (
    AppointmentNotFoundError,
    get_appointment,
    list_all_appointments,
    list_patient_appointments,
)
from app.services.department_service import list_departments
from app.services.reminder_service import get_reminder, list_appointment_reminders
from app.tools.appointment_tool import (
    try_book_appointment,
    try_cancel_appointment,
    try_reschedule_appointment,
)
from app.tools.reminder_tool import notify, schedule_reminder
from app.tools.slot_tool import find_available_slots

router = APIRouter(prefix="/appointments", tags=["appointments"])


@router.get("/departments", response_model=list[DepartmentOut])
def list_departments_for_booking(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Any authenticated user can see active departments — needed by
    patients to choose where to book, distinct from the staff-only
    department *management* endpoints in routes_staff.py."""
    return list_departments(db, active_only=True)


@router.get("/slots")
def browse_available_slots(
    department_id: int | None = None,
    doctor_id: int | None = None,
    start_after: datetime | None = None,
    start_before: datetime | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    return find_available_slots(
        db,
        department_id=department_id,
        doctor_id=doctor_id,
        start_after=start_after,
        start_before=start_before,
    )


@router.post("", response_model=AppointmentOut, status_code=status.HTTP_201_CREATED)
def book(
    payload: AppointmentCreateRequest,
    db: Session = Depends(get_db),
    patient: PatientProfile = Depends(get_current_patient_profile),
):
    result = try_book_appointment(db, patient, payload.slot_id, payload.reason)
    if result["status"] != "booked":
        code = status.HTTP_409_CONFLICT
        raise HTTPException(status_code=code, detail=result["detail"])
    return get_appointment(db, result["appointment_id"])


@router.get("")
def list_appointments(
    patient_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[AppointmentOut]:
    if current_user.role == UserRole.PATIENT:
        profile = get_current_patient_profile(current_user=current_user, db=db)
        appointments = list_patient_appointments(db, profile.id)
    else:
        appointments = list_all_appointments(db, patient_id=patient_id)
    return [AppointmentOut.model_validate(a) for a in appointments]


@router.get("/{appointment_id}", response_model=AppointmentOut)
def get_one(
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

    return appointment


@router.post("/{appointment_id}/reschedule", response_model=AppointmentOut)
def reschedule(
    appointment_id: int,
    payload: RescheduleRequest,
    db: Session = Depends(get_db),
    patient: PatientProfile = Depends(get_current_patient_profile),
):
    try:
        get_appointment(db, appointment_id)
    except AppointmentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    result = try_reschedule_appointment(db, patient, appointment_id, payload.new_slot_id)
    if result["status"] == "forbidden":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=result["detail"])
    if result["status"] != "rescheduled":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=result["detail"])
    return get_appointment(db, appointment_id)


@router.post("/{appointment_id}/cancel", response_model=AppointmentOut)
def cancel(
    appointment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        appointment = get_appointment(db, appointment_id)
    except AppointmentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    patient_scope = None
    if current_user.role == UserRole.PATIENT:
        patient_scope = get_current_patient_profile(current_user=current_user, db=db)
        if appointment.patient_id != patient_scope.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your appointment")

    result = try_cancel_appointment(db, current_user, appointment_id, patient_scope)
    if result["status"] != "cancelled":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=result["detail"])
    return get_appointment(db, appointment_id)


def _assert_can_view_appointment(db: Session, current_user: User, appointment_id: int):
    try:
        appointment = get_appointment(db, appointment_id)
    except AppointmentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    if current_user.role == UserRole.PATIENT:
        profile = get_current_patient_profile(current_user=current_user, db=db)
        if appointment.patient_id != profile.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your appointment")
    return appointment


@router.post(
    "/{appointment_id}/reminders", response_model=ReminderOut, status_code=status.HTTP_201_CREATED
)
def create_appointment_reminder(
    appointment_id: int,
    payload: ReminderCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    appointment = _assert_can_view_appointment(db, current_user, appointment_id)
    if current_user.role == UserRole.PATIENT:
        patient = get_current_patient_profile(current_user=current_user, db=db)
    else:
        patient = db.get(PatientProfile, appointment.patient_id)

    result = schedule_reminder(
        db,
        actor_id=current_user.id,
        actor_role=current_user.role.value,
        patient=patient,
        reminder_type=payload.reminder_type,
        scheduled_at=payload.scheduled_at,
        appointment_id=appointment_id,
    )
    if result["status"] != "scheduled":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=result["detail"])

    return get_reminder(db, result["reminder_id"])


@router.get("/{appointment_id}/reminders", response_model=list[ReminderOut])
def list_appointment_reminders_route(
    appointment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _assert_can_view_appointment(db, current_user, appointment_id)
    return list_appointment_reminders(db, appointment_id)


@router.post("/reminders/{reminder_id}/send", response_model=NotificationLogOut)
def send_reminder_notification(
    reminder_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.STAFF, UserRole.ADMIN)),
):
    result = notify(db, reminder_id)
    if result["status"] == "not_found":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=result["detail"])
    if result["status"] != "sent":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=result["detail"])

    return db.get(NotificationLog, result["notification_id"])
