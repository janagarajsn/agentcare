from sqlalchemy.orm import Session

from app.db.models import PatientProfile
from app.tools.audit_tool import record_audit_event


def update_patient_profile(db: Session, patient: PatientProfile, payload) -> PatientProfile:
    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(patient, field, value)

    record_audit_event(
        db,
        actor_id=patient.user_id,
        actor_role="patient",
        action="patient_profile_updated",
        entity_type="PatientProfile",
        entity_id=patient.id,
        metadata={"fields": list(updates.keys())},
    )
    db.commit()
    db.refresh(patient)
    return patient
