"""Synthetic reference data for local development and demos.

Populates departments, doctors, appointment slots, and a handful of
patient/staff/admin accounts. Contains no real patient data — all names,
emails, and identifiers below are fabricated for testing only.

Run with: python -m app.seed.seed_data
"""

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.auth.security import hash_password
from app.db.models import (
    AppointmentSlot,
    Department,
    Doctor,
    PatientProfile,
    SlotStatus,
    User,
    UserRole,
)
from app.db.session import SessionLocal

DEPARTMENTS = [
    ("Cardiology", "Heart and cardiovascular care"),
    ("Orthopedics", "Bones, joints, and musculoskeletal care"),
    ("Dermatology", "Skin, hair, and nail conditions"),
    ("General Medicine", "General adult primary care"),
    ("Pediatrics", "Care for infants, children, and adolescents"),
    ("ENT", "Ear, nose, and throat care"),
]

DOCTORS_BY_DEPARTMENT = {
    "Cardiology": ["Dr. Asha Rao", "Dr. Miles Okafor"],
    "Orthopedics": ["Dr. Priya Nair"],
    "Dermatology": ["Dr. Lena Fischer"],
    "General Medicine": ["Dr. Sam Patel", "Dr. Rina Gomez"],
    "Pediatrics": ["Dr. Wei Zhang"],
    "ENT": ["Dr. Omar Haddad"],
}

DEMO_USERS = [
    {
        "name": "Patient One",
        "email": "patient1@agentcare.example",
        "password": "Patient123!",
        "role": UserRole.PATIENT,
        "profile": {
            "date_of_birth": datetime(1990, 4, 12).date(),
            "phone": "+1-555-0101",
            "preferred_language": "en",
            "emergency_contact": "Jordan One, +1-555-0102",
        },
    },
    {
        "name": "Patient Two",
        "email": "patient2@agentcare.example",
        "password": "Patient123!",
        "role": UserRole.PATIENT,
        "profile": {
            "date_of_birth": datetime(1985, 11, 2).date(),
            "phone": "+1-555-0201",
            "preferred_language": "en",
            "emergency_contact": "Casey Two, +1-555-0202",
        },
    },
    {
        "name": "Staff Member",
        "email": "staff1@agentcare.example",
        "password": "Staff123!",
        "role": UserRole.STAFF,
        "profile": None,
    },
    {
        "name": "Admin User",
        "email": "admin1@agentcare.example",
        "password": "Admin123!",
        "role": UserRole.ADMIN,
        "profile": None,
    },
]

SLOT_HOURS = [9, 10, 11, 14, 15, 16]
SLOT_DAYS_AHEAD = 10


def _seed_departments_and_doctors(db: Session) -> dict[str, Doctor]:
    doctors_by_name: dict[str, Doctor] = {}

    for name, description in DEPARTMENTS:
        department = db.query(Department).filter_by(name=name).first()
        if department is None:
            department = Department(name=name, description=description, active=True)
            db.add(department)
            db.flush()

        for doctor_name in DOCTORS_BY_DEPARTMENT[name]:
            doctor = (
                db.query(Doctor)
                .filter_by(name=doctor_name, department_id=department.id)
                .first()
            )
            if doctor is None:
                doctor = Doctor(name=doctor_name, department_id=department.id, active=True)
                db.add(doctor)
                db.flush()
            doctors_by_name[doctor_name] = doctor

    return doctors_by_name


def _seed_slots(db: Session, doctors_by_name: dict[str, Doctor]) -> None:
    today = datetime.now().replace(minute=0, second=0, microsecond=0)

    for doctor in doctors_by_name.values():
        existing_slot_count = db.query(AppointmentSlot).filter_by(doctor_id=doctor.id).count()
        if existing_slot_count > 0:
            continue

        for day_offset in range(1, SLOT_DAYS_AHEAD + 1):
            slot_day = today + timedelta(days=day_offset)
            if slot_day.weekday() >= 5:  # skip weekends
                continue
            for hour in SLOT_HOURS:
                start = slot_day.replace(hour=hour)
                end = start + timedelta(minutes=30)
                db.add(
                    AppointmentSlot(
                        doctor_id=doctor.id,
                        start_time=start,
                        end_time=end,
                        status=SlotStatus.OPEN,
                    )
                )


def _seed_users(db: Session) -> None:
    for entry in DEMO_USERS:
        user = db.query(User).filter_by(email=entry["email"]).first()
        if user is not None:
            continue

        user = User(
            name=entry["name"],
            email=entry["email"],
            password_hash=hash_password(entry["password"]),
            role=entry["role"],
            is_active=True,
        )
        db.add(user)
        db.flush()

        if entry["profile"] is not None:
            db.add(PatientProfile(user_id=user.id, **entry["profile"]))


def seed(db: Session) -> None:
    doctors_by_name = _seed_departments_and_doctors(db)
    _seed_slots(db, doctors_by_name)
    _seed_users(db)
    db.commit()


def main() -> None:
    db = SessionLocal()
    try:
        seed(db)
        print("Seed complete.")
        print("Demo accounts (local/dev only, not real people):")
        for entry in DEMO_USERS:
            print(f"  {entry['role'].value:8s} {entry['email']:28s} password={entry['password']}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
