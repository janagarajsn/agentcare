from datetime import datetime

from sqlalchemy.orm import Session

from app.db.models import AppointmentSlot, Doctor, SlotStatus, User
from app.tools.audit_tool import record_audit_event


class SlotNotFoundError(Exception):
    pass


class SlotOverlapError(Exception):
    pass


class DoctorNotFoundError(Exception):
    pass


def get_slot(db: Session, slot_id: int) -> AppointmentSlot:
    slot = db.get(AppointmentSlot, slot_id)
    if slot is None:
        raise SlotNotFoundError(f"Slot {slot_id} not found")
    return slot


def create_slot(db: Session, actor: User, doctor_id: int, start_time: datetime, end_time: datetime) -> AppointmentSlot:
    doctor = db.get(Doctor, doctor_id)
    if doctor is None:
        raise DoctorNotFoundError(f"Doctor {doctor_id} not found")

    overlapping = (
        db.query(AppointmentSlot)
        .filter(
            AppointmentSlot.doctor_id == doctor_id,
            AppointmentSlot.status != SlotStatus.CANCELLED,
            AppointmentSlot.start_time < end_time,
            AppointmentSlot.end_time > start_time,
        )
        .first()
    )
    if overlapping is not None:
        raise SlotOverlapError(
            f"Doctor {doctor_id} already has a slot overlapping {start_time.isoformat()}-{end_time.isoformat()}"
        )

    slot = AppointmentSlot(doctor_id=doctor_id, start_time=start_time, end_time=end_time, status=SlotStatus.OPEN)
    db.add(slot)
    db.flush()

    record_audit_event(
        db,
        actor_id=actor.id,
        actor_role=actor.role.value,
        action="slot_created",
        entity_type="AppointmentSlot",
        entity_id=slot.id,
        metadata={"doctor_id": doctor_id, "start_time": start_time.isoformat()},
    )
    db.commit()
    db.refresh(slot)
    return slot


def list_available_slots(
    db: Session,
    *,
    department_id: int | None = None,
    doctor_id: int | None = None,
    start_after: datetime | None = None,
    start_before: datetime | None = None,
) -> list[AppointmentSlot]:
    query = db.query(AppointmentSlot).filter(AppointmentSlot.status == SlotStatus.OPEN)

    if doctor_id is not None:
        query = query.filter(AppointmentSlot.doctor_id == doctor_id)
    if department_id is not None:
        query = query.join(Doctor, AppointmentSlot.doctor_id == Doctor.id).filter(
            Doctor.department_id == department_id
        )
    if start_after is not None:
        query = query.filter(AppointmentSlot.start_time >= start_after)
    if start_before is not None:
        query = query.filter(AppointmentSlot.start_time <= start_before)

    return query.order_by(AppointmentSlot.start_time).all()
