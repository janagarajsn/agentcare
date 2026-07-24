from sqlalchemy.orm import Session

from app.db.models import PatientProfile, User
from app.tools.audit_tool import record_audit_event


def find_or_create_patient_profile(db: Session, user: User) -> dict:
    """Ensure a PatientProfile exists for this authenticated user.

    Real branching: normally the profile already exists from registration;
    this only creates a minimal one on the (edge-case) path where it's
    missing, and records that in the audit trail either way.
    """
    profile = db.query(PatientProfile).filter_by(user_id=user.id).first()
    created = False

    if profile is None:
        profile = PatientProfile(user_id=user.id, preferred_language="en")
        db.add(profile)
        db.flush()
        created = True

        record_audit_event(
            db,
            actor_id=user.id,
            actor_role=user.role.value,
            action="patient_profile_auto_created",
            entity_type="PatientProfile",
            entity_id=profile.id,
            metadata={"reason": "missing_profile_at_workflow_start"},
        )
        db.commit()
        db.refresh(profile)

    return {
        "patient_id": profile.id,
        "created": created,
        "preferred_language": profile.preferred_language,
        "has_emergency_contact": bool(profile.emergency_contact),
    }
