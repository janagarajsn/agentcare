from sqlalchemy.orm import Session

from app.db.models import (
    Appointment,
    AppointmentStatus,
    AppointmentSlot,
    PatientProfile,
    Reminder,
    ReminderStatus,
    SlotStatus,
    User,
)
from app.tools.audit_tool import record_audit_event

_ACTIVE_APPOINTMENT_STATUSES = (
    AppointmentStatus.PENDING,
    AppointmentStatus.CONFIRMED,
    AppointmentStatus.RESCHEDULED,
)


class AppointmentNotFoundError(Exception):
    pass


class SlotUnavailableError(Exception):
    pass


class AppointmentConflictError(Exception):
    pass


class AppointmentStateError(Exception):
    pass


class NotOwnerError(Exception):
    pass


def get_appointment(db: Session, appointment_id: int) -> Appointment:
    appointment = db.get(Appointment, appointment_id)
    if appointment is None:
        raise AppointmentNotFoundError(f"Appointment {appointment_id} not found")
    return appointment


def _assert_owned_by_patient(appointment: Appointment, patient: PatientProfile) -> None:
    if appointment.patient_id != patient.id:
        raise NotOwnerError("This appointment does not belong to the current patient")


def _find_patient_time_conflict(
    db: Session, patient_id: int, slot: AppointmentSlot, exclude_appointment_id: int | None = None
) -> Appointment | None:
    query = (
        db.query(Appointment)
        .join(AppointmentSlot, Appointment.slot_id == AppointmentSlot.id)
        .filter(
            Appointment.patient_id == patient_id,
            Appointment.status.in_(_ACTIVE_APPOINTMENT_STATUSES),
            AppointmentSlot.start_time < slot.end_time,
            AppointmentSlot.end_time > slot.start_time,
        )
    )
    if exclude_appointment_id is not None:
        query = query.filter(Appointment.id != exclude_appointment_id)
    return query.first()


def book_appointment(db: Session, patient: PatientProfile, slot_id: int, reason: str | None) -> Appointment:
    slot = db.get(AppointmentSlot, slot_id)
    if slot is None:
        raise SlotUnavailableError(f"Slot {slot_id} not found")
    if slot.status != SlotStatus.OPEN:
        raise SlotUnavailableError(f"Slot {slot_id} is no longer available")

    conflict = _find_patient_time_conflict(db, patient.id, slot)
    if conflict is not None:
        raise AppointmentConflictError(
            f"Patient already has appointment {conflict.id} overlapping this time slot"
        )

    slot.status = SlotStatus.BOOKED
    appointment = Appointment(
        patient_id=patient.id,
        doctor_id=slot.doctor_id,
        slot_id=slot.id,
        status=AppointmentStatus.CONFIRMED,
        reason=reason,
    )
    db.add(appointment)
    db.flush()

    record_audit_event(
        db,
        actor_id=patient.user_id,
        actor_role="patient",
        action="appointment_booked",
        entity_type="Appointment",
        entity_id=appointment.id,
        metadata={"slot_id": slot.id, "doctor_id": slot.doctor_id},
    )
    db.commit()
    db.refresh(appointment)
    return appointment


def reschedule_appointment(
    db: Session, patient: PatientProfile, appointment_id: int, new_slot_id: int
) -> Appointment:
    appointment = get_appointment(db, appointment_id)
    _assert_owned_by_patient(appointment, patient)

    if appointment.status not in _ACTIVE_APPOINTMENT_STATUSES:
        raise AppointmentStateError(f"Appointment {appointment_id} cannot be rescheduled from status {appointment.status.value}")

    new_slot = db.get(AppointmentSlot, new_slot_id)
    if new_slot is None:
        raise SlotUnavailableError(f"Slot {new_slot_id} not found")
    if new_slot.status != SlotStatus.OPEN:
        raise SlotUnavailableError(f"Slot {new_slot_id} is no longer available")

    conflict = _find_patient_time_conflict(db, patient.id, new_slot, exclude_appointment_id=appointment.id)
    if conflict is not None:
        raise AppointmentConflictError(
            f"Patient already has appointment {conflict.id} overlapping this time slot"
        )

    old_slot = db.get(AppointmentSlot, appointment.slot_id)
    old_slot_id = old_slot.id if old_slot else None
    if old_slot is not None:
        old_slot.status = SlotStatus.OPEN

    new_slot.status = SlotStatus.BOOKED
    appointment.slot_id = new_slot.id
    appointment.doctor_id = new_slot.doctor_id
    appointment.status = AppointmentStatus.RESCHEDULED

    record_audit_event(
        db,
        actor_id=patient.user_id,
        actor_role="patient",
        action="appointment_rescheduled",
        entity_type="Appointment",
        entity_id=appointment.id,
        metadata={"old_slot_id": old_slot_id, "new_slot_id": new_slot.id},
    )
    db.commit()
    db.refresh(appointment)
    return appointment


def cancel_appointment(db: Session, actor: User, appointment_id: int, patient: PatientProfile | None = None) -> Appointment:
    appointment = get_appointment(db, appointment_id)
    if patient is not None:
        _assert_owned_by_patient(appointment, patient)

    if appointment.status == AppointmentStatus.CANCELLED:
        raise AppointmentStateError(f"Appointment {appointment_id} is already cancelled")
    if appointment.status == AppointmentStatus.COMPLETED:
        raise AppointmentStateError(f"Appointment {appointment_id} is already completed and cannot be cancelled")

    slot = db.get(AppointmentSlot, appointment.slot_id)
    if slot is not None:
        slot.status = SlotStatus.OPEN

    appointment.status = AppointmentStatus.CANCELLED

    record_audit_event(
        db,
        actor_id=actor.id,
        actor_role=actor.role.value,
        action="appointment_cancelled",
        entity_type="Appointment",
        entity_id=appointment.id,
        metadata={"slot_id": appointment.slot_id},
    )

    # A reminder scheduled for a visit that's no longer happening (or a
    # post-visit follow-up for a visit that never happened) is stale, not
    # useful — cancel it too rather than leaving it to fire pointlessly.
    scheduled_reminders = (
        db.query(Reminder)
        .filter_by(appointment_id=appointment.id, status=ReminderStatus.SCHEDULED)
        .all()
    )
    for reminder in scheduled_reminders:
        reminder.status = ReminderStatus.CANCELLED
        record_audit_event(
            db,
            actor_id=actor.id,
            actor_role=actor.role.value,
            action="reminder_cancelled",
            entity_type="Reminder",
            entity_id=reminder.id,
            metadata={"appointment_id": appointment.id, "reason": "appointment_cancelled"},
        )

    db.commit()
    db.refresh(appointment)
    return appointment


def list_patient_appointments(db: Session, patient_id: int) -> list[Appointment]:
    return (
        db.query(Appointment)
        .filter_by(patient_id=patient_id)
        .order_by(Appointment.created_at.desc())
        .all()
    )


def list_all_appointments(db: Session, patient_id: int | None = None) -> list[Appointment]:
    query = db.query(Appointment)
    if patient_id is not None:
        query = query.filter_by(patient_id=patient_id)
    return query.order_by(Appointment.created_at.desc()).all()
