from datetime import datetime

from sqlalchemy.orm import Session

from app.auth.security import hash_password, verify_password
from app.db.models import PatientProfile, User, UserRole
from app.schemas.auth import PatientRegisterRequest, StaffCreateRequest
from app.tools.audit_tool import record_audit_event


class EmailAlreadyRegisteredError(Exception):
    pass


class InvalidCredentialsError(Exception):
    pass


def register_patient(db: Session, payload: PatientRegisterRequest) -> User:
    existing = db.query(User).filter_by(email=payload.email).first()
    if existing is not None:
        raise EmailAlreadyRegisteredError(f"Email {payload.email} is already registered")

    user = User(
        name=payload.name,
        email=payload.email,
        password_hash=hash_password(payload.password),
        role=UserRole.PATIENT,
        is_active=True,
    )
    db.add(user)
    db.flush()

    profile = PatientProfile(
        user_id=user.id,
        date_of_birth=payload.date_of_birth,
        phone=payload.phone,
        preferred_language=payload.preferred_language,
        emergency_contact=payload.emergency_contact,
    )
    db.add(profile)
    db.flush()

    record_audit_event(
        db,
        actor_id=user.id,
        actor_role=UserRole.PATIENT.value,
        action="patient_registered",
        entity_type="User",
        entity_id=user.id,
        metadata={"email": user.email},
    )
    db.commit()
    db.refresh(user)
    return user


def create_staff_user(db: Session, creator: User, payload: StaffCreateRequest) -> User:
    role = payload.validated_role()

    existing = db.query(User).filter_by(email=payload.email).first()
    if existing is not None:
        raise EmailAlreadyRegisteredError(f"Email {payload.email} is already registered")

    user = User(
        name=payload.name,
        email=payload.email,
        password_hash=hash_password(payload.password),
        role=role,
        is_active=True,
    )
    db.add(user)
    db.flush()

    record_audit_event(
        db,
        actor_id=creator.id,
        actor_role=creator.role.value,
        action="staff_account_created",
        entity_type="User",
        entity_id=user.id,
        metadata={"email": user.email, "assigned_role": role.value},
    )
    db.commit()
    db.refresh(user)
    return user


def authenticate_user(db: Session, email: str, password: str) -> User:
    user = db.query(User).filter_by(email=email).first()
    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        raise InvalidCredentialsError("Incorrect email or password")

    user.last_login_at = datetime.utcnow()
    record_audit_event(
        db,
        actor_id=user.id,
        actor_role=user.role.value,
        action="login_succeeded",
        entity_type="User",
        entity_id=user.id,
        metadata={},
    )
    db.commit()
    db.refresh(user)
    return user
