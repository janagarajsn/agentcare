from datetime import datetime

from sqlalchemy.orm import Session

from app.services.slot_service import list_available_slots


def find_available_slots(
    db: Session,
    *,
    department_id: int | None = None,
    doctor_id: int | None = None,
    start_after: datetime | None = None,
    start_before: datetime | None = None,
) -> dict:
    """Real availability lookup against persisted slots — filters by
    department/doctor/date range and returns only OPEN slots."""
    slots = list_available_slots(
        db,
        department_id=department_id,
        doctor_id=doctor_id,
        start_after=start_after,
        start_before=start_before,
    )
    return {
        "count": len(slots),
        "slots": [
            {
                "slot_id": s.id,
                "doctor_id": s.doctor_id,
                "start_time": s.start_time.isoformat(),
                "end_time": s.end_time.isoformat(),
            }
            for s in slots
        ],
    }
