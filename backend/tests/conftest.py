import os
import tempfile
from collections.abc import Generator
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.auth.security import create_access_token, hash_password
from app.db import models  # noqa: F401 -- ensures all models are registered on Base.metadata
from app.db.base import Base
from app.db.models import (
    AppointmentSlot,
    Department,
    Doctor,
    PatientProfile,
    SlotStatus,
    User,
    UserRole,
)
from app.db.session import get_db


@pytest.fixture()
def db_session() -> Generator[Session, None, None]:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    session = TestSessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
        os.remove(path)


@pytest.fixture()
def client(db_session: Session) -> Generator[TestClient, None, None]:
    from app.main import app

    def _get_db_override() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = _get_db_override
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _make_user(db_session: Session, *, name: str, email: str, password: str, role: UserRole) -> User:
    user = User(
        name=name,
        email=email,
        password_hash=hash_password(password),
        role=role,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture()
def staff_user(db_session: Session) -> User:
    return _make_user(
        db_session, name="Staff Tester", email="staff.tester@agentcare.example",
        password="StaffPass123!", role=UserRole.STAFF,
    )


@pytest.fixture()
def admin_user(db_session: Session) -> User:
    return _make_user(
        db_session, name="Admin Tester", email="admin.tester@agentcare.example",
        password="AdminPass123!", role=UserRole.ADMIN,
    )


def auth_headers(user: User) -> dict:
    token = create_access_token(user.id, user.role.value)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def patient_with_profile(db_session: Session) -> tuple[User, PatientProfile]:
    user = _make_user(
        db_session, name="Fixture Patient", email="fixture.patient@agentcare.example",
        password="FixturePass123!", role=UserRole.PATIENT,
    )
    profile = PatientProfile(user_id=user.id, preferred_language="en")
    db_session.add(profile)
    db_session.commit()
    db_session.refresh(profile)
    return user, profile


@pytest.fixture()
def second_patient_with_profile(db_session: Session) -> tuple[User, PatientProfile]:
    user = _make_user(
        db_session, name="Second Patient", email="second.patient@agentcare.example",
        password="SecondPass123!", role=UserRole.PATIENT,
    )
    profile = PatientProfile(user_id=user.id, preferred_language="en")
    db_session.add(profile)
    db_session.commit()
    db_session.refresh(profile)
    return user, profile


@pytest.fixture()
def cardiology_department(db_session: Session) -> Department:
    department = Department(name="Cardiology", description="Heart care", active=True)
    db_session.add(department)
    db_session.commit()
    db_session.refresh(department)
    return department


@pytest.fixture()
def cardiologist(db_session: Session, cardiology_department: Department) -> Doctor:
    doctor = Doctor(department_id=cardiology_department.id, name="Dr. Fixture Cardio", active=True)
    db_session.add(doctor)
    db_session.commit()
    db_session.refresh(doctor)
    return doctor


@pytest.fixture()
def open_slot(db_session: Session, cardiologist: Doctor) -> AppointmentSlot:
    start = datetime(2030, 1, 7, 9, 0)
    slot = AppointmentSlot(
        doctor_id=cardiologist.id, start_time=start, end_time=start + timedelta(minutes=30),
        status=SlotStatus.OPEN,
    )
    db_session.add(slot)
    db_session.commit()
    db_session.refresh(slot)
    return slot


@pytest.fixture()
def another_open_slot(db_session: Session, cardiologist: Doctor) -> AppointmentSlot:
    start = datetime(2030, 1, 7, 10, 0)
    slot = AppointmentSlot(
        doctor_id=cardiologist.id, start_time=start, end_time=start + timedelta(minutes=30),
        status=SlotStatus.OPEN,
    )
    db_session.add(slot)
    db_session.commit()
    db_session.refresh(slot)
    return slot


@pytest.fixture()
def overlapping_slot(db_session: Session, cardiologist: Doctor) -> AppointmentSlot:
    start = datetime(2030, 1, 7, 9, 15)
    slot = AppointmentSlot(
        doctor_id=cardiologist.id, start_time=start, end_time=start + timedelta(minutes=30),
        status=SlotStatus.OPEN,
    )
    db_session.add(slot)
    db_session.commit()
    db_session.refresh(slot)
    return slot
