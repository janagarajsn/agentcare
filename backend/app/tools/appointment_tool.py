from sqlalchemy.orm import Session

from app.db.models import PatientProfile, User
from app.services.appointment_service import (
    AppointmentConflictError,
    AppointmentNotFoundError,
    AppointmentStateError,
    NotOwnerError,
    SlotUnavailableError,
    book_appointment,
    cancel_appointment,
    list_patient_appointments,
    reschedule_appointment,
)

_ACTIVE_STATUSES = {"pending", "confirmed", "rescheduled"}


def list_my_active_appointments(db: Session, patient: PatientProfile) -> dict:
    """Look up the current patient's own active appointments — used to
    resolve implicit references like "my appointment" or "my upcoming
    visit" to a real appointment_id when the request doesn't state one
    explicitly."""
    appointments = [
        {
            "appointment_id": a.id,
            "doctor_name": a.doctor.name,
            "department_name": a.doctor.department.name,
            "slot_start_time": a.slot.start_time.isoformat(),
            "slot_end_time": a.slot.end_time.isoformat(),
            "status": a.status.value,
            "reason": a.reason,
        }
        for a in list_patient_appointments(db, patient.id)
        if a.status.value in _ACTIVE_STATUSES
    ]
    return {"count": len(appointments), "appointments": appointments}


def try_book_appointment(db: Session, patient: PatientProfile, slot_id: int, reason: str | None) -> dict:
    """Attempt to book a slot; returns a structured result instead of raising
    so a calling agent can branch on outcome (e.g. escalate on repeated conflicts)."""
    try:
        appointment = book_appointment(db, patient, slot_id, reason)
    except SlotUnavailableError as exc:
        return {"status": "slot_unavailable", "detail": str(exc)}
    except AppointmentConflictError as exc:
        return {"status": "conflict", "detail": str(exc)}

    return {
        "status": "booked",
        "appointment_id": appointment.id,
        "doctor_id": appointment.doctor_id,
        "slot_id": appointment.slot_id,
        "appointment_status": appointment.status.value,
    }


def try_reschedule_appointment(
    db: Session, patient: PatientProfile, appointment_id: int, new_slot_id: int
) -> dict:
    try:
        appointment = reschedule_appointment(db, patient, appointment_id, new_slot_id)
    except AppointmentNotFoundError as exc:
        return {"status": "not_found", "detail": str(exc)}
    except SlotUnavailableError as exc:
        return {"status": "slot_unavailable", "detail": str(exc)}
    except AppointmentConflictError as exc:
        return {"status": "conflict", "detail": str(exc)}
    except AppointmentStateError as exc:
        return {"status": "invalid_state", "detail": str(exc)}
    except NotOwnerError as exc:
        return {"status": "forbidden", "detail": str(exc)}

    return {
        "status": "rescheduled",
        "appointment_id": appointment.id,
        "slot_id": appointment.slot_id,
        "appointment_status": appointment.status.value,
    }


def try_cancel_appointment(
    db: Session, actor: User, appointment_id: int, patient: PatientProfile | None = None
) -> dict:
    try:
        appointment = cancel_appointment(db, actor, appointment_id, patient)
    except AppointmentNotFoundError as exc:
        return {"status": "not_found", "detail": str(exc)}
    except AppointmentStateError as exc:
        return {"status": "invalid_state", "detail": str(exc)}

    return {"status": "cancelled", "appointment_id": appointment.id}
