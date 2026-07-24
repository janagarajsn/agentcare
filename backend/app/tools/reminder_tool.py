from datetime import datetime

from sqlalchemy.orm import Session

from app.db.models import PatientProfile, ReminderType
from app.services.reminder_service import (
    AppointmentOwnershipError,
    ReminderAlreadySentError,
    ReminderNotFoundError,
    create_reminder,
    send_notification,
)


def schedule_reminder(
    db: Session,
    *,
    actor_id: int,
    actor_role: str,
    patient: PatientProfile,
    reminder_type: ReminderType,
    scheduled_at: datetime,
    appointment_id: int | None = None,
) -> dict:
    try:
        reminder = create_reminder(
            db,
            actor_id=actor_id,
            actor_role=actor_role,
            patient=patient,
            reminder_type=reminder_type,
            scheduled_at=scheduled_at,
            appointment_id=appointment_id,
        )
    except AppointmentOwnershipError as exc:
        return {"status": "appointment_not_found", "detail": str(exc)}

    return {"status": "scheduled", "reminder_id": reminder.id}


def notify(db: Session, reminder_id: int, channel: str = "in_app") -> dict:
    try:
        log_entry = send_notification(db, reminder_id, channel=channel)
    except ReminderNotFoundError as exc:
        return {"status": "not_found", "detail": str(exc)}
    except ReminderAlreadySentError as exc:
        return {"status": "already_sent", "detail": str(exc)}

    return {"status": "sent", "notification_id": log_entry.id, "message": log_entry.message}
