from datetime import datetime

from sqlalchemy.orm import Session

from app.db.models import (
    Appointment,
    NotificationLog,
    PatientProfile,
    Reminder,
    ReminderStatus,
    ReminderType,
)
from app.tools.audit_tool import record_audit_event


class ReminderNotFoundError(Exception):
    pass


class AppointmentOwnershipError(Exception):
    pass


class ReminderAlreadySentError(Exception):
    pass


def create_reminder(
    db: Session,
    *,
    actor_id: int,
    actor_role: str,
    patient: PatientProfile,
    reminder_type: ReminderType,
    scheduled_at: datetime,
    appointment_id: int | None = None,
) -> Reminder:
    if appointment_id is not None:
        appointment = db.get(Appointment, appointment_id)
        if appointment is None or appointment.patient_id != patient.id:
            raise AppointmentOwnershipError(
                f"Appointment {appointment_id} not found for this patient"
            )

    reminder = Reminder(
        patient_id=patient.id,
        appointment_id=appointment_id,
        reminder_type=reminder_type,
        scheduled_at=scheduled_at,
        status=ReminderStatus.SCHEDULED,
    )
    db.add(reminder)
    db.flush()

    record_audit_event(
        db,
        actor_id=actor_id,
        actor_role=actor_role,
        action="reminder_created",
        entity_type="Reminder",
        entity_id=reminder.id,
        metadata={"reminder_type": reminder_type.value, "appointment_id": appointment_id},
    )
    db.commit()
    db.refresh(reminder)
    return reminder


def upsert_appointment_reminder(
    db: Session,
    *,
    actor_id: int,
    actor_role: str,
    patient: PatientProfile,
    reminder_type: ReminderType,
    scheduled_at: datetime,
    appointment_id: int,
) -> Reminder:
    """Create a reminder of this type for this appointment, or if one is
    already SCHEDULED (not yet sent), update its time in place instead of
    creating a duplicate. Without this, rescheduling an appointment (or the
    agent pipeline simply re-running) leaves stale reminder rows behind
    that still point at the appointment's old time."""
    appointment = db.get(Appointment, appointment_id)
    if appointment is None or appointment.patient_id != patient.id:
        raise AppointmentOwnershipError(f"Appointment {appointment_id} not found for this patient")

    existing = (
        db.query(Reminder)
        .filter_by(appointment_id=appointment_id, reminder_type=reminder_type, status=ReminderStatus.SCHEDULED)
        .first()
    )
    if existing is not None:
        if existing.scheduled_at != scheduled_at:
            existing.scheduled_at = scheduled_at
            record_audit_event(
                db,
                actor_id=actor_id,
                actor_role=actor_role,
                action="reminder_rescheduled",
                entity_type="Reminder",
                entity_id=existing.id,
                metadata={"reminder_type": reminder_type.value, "appointment_id": appointment_id},
            )
            db.commit()
            db.refresh(existing)
        return existing

    return create_reminder(
        db,
        actor_id=actor_id,
        actor_role=actor_role,
        patient=patient,
        reminder_type=reminder_type,
        scheduled_at=scheduled_at,
        appointment_id=appointment_id,
    )


def get_reminder(db: Session, reminder_id: int) -> Reminder:
    reminder = db.get(Reminder, reminder_id)
    if reminder is None:
        raise ReminderNotFoundError(f"Reminder {reminder_id} not found")
    return reminder


def _build_notification_message(reminder: Reminder) -> str:
    if reminder.appointment_id is not None:
        appointment = reminder.appointment
        doctor_name = appointment.doctor.name if appointment else "your doctor"
        slot = appointment.slot if appointment else None
        when = slot.start_time.strftime("%Y-%m-%d %H:%M") if slot else "the scheduled time"
        return (
            f"[{reminder.reminder_type.value}] Reminder for your appointment with "
            f"{doctor_name} at {when}."
        )
    return f"[{reminder.reminder_type.value}] Reminder scheduled for {reminder.scheduled_at.strftime('%Y-%m-%d %H:%M')}."


def send_notification(db: Session, reminder_id: int, channel: str = "in_app") -> NotificationLog:
    reminder = get_reminder(db, reminder_id)
    if reminder.status == ReminderStatus.SENT:
        raise ReminderAlreadySentError(f"Reminder {reminder_id} has already been sent")

    message = _build_notification_message(reminder)
    log_entry = NotificationLog(reminder_id=reminder.id, channel=channel, message=message)
    db.add(log_entry)

    reminder.status = ReminderStatus.SENT

    record_audit_event(
        db,
        actor_id=None,
        actor_role="system",
        action="notification_sent",
        entity_type="Reminder",
        entity_id=reminder.id,
        metadata={"channel": channel},
    )
    db.commit()
    db.refresh(log_entry)
    return log_entry


def list_patient_reminders(db: Session, patient_id: int) -> list[Reminder]:
    return (
        db.query(Reminder)
        .filter_by(patient_id=patient_id)
        .order_by(Reminder.scheduled_at)
        .all()
    )


def list_appointment_reminders(db: Session, appointment_id: int) -> list[Reminder]:
    return (
        db.query(Reminder)
        .filter_by(appointment_id=appointment_id)
        .order_by(Reminder.scheduled_at)
        .all()
    )
