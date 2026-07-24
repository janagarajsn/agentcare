from sqlalchemy.orm import Session

from app.db.models import Department, Doctor, User
from app.tools.audit_tool import record_audit_event


class DepartmentNotFoundError(Exception):
    pass


class DepartmentInactiveError(Exception):
    pass


class DuplicateDepartmentError(Exception):
    pass


def list_departments(db: Session, *, active_only: bool = True) -> list[Department]:
    query = db.query(Department)
    if active_only:
        query = query.filter_by(active=True)
    return query.order_by(Department.name).all()


def get_department(db: Session, department_id: int) -> Department:
    department = db.get(Department, department_id)
    if department is None:
        raise DepartmentNotFoundError(f"Department {department_id} not found")
    return department


def find_department_by_name(db: Session, name: str) -> Department | None:
    return db.query(Department).filter(Department.name.ilike(name.strip())).first()


def create_department(db: Session, actor: User, payload) -> Department:
    existing = find_department_by_name(db, payload.name)
    if existing is not None:
        raise DuplicateDepartmentError(f"Department '{payload.name}' already exists")

    department = Department(name=payload.name, description=payload.description, active=True)
    db.add(department)
    db.flush()

    record_audit_event(
        db,
        actor_id=actor.id,
        actor_role=actor.role.value,
        action="department_created",
        entity_type="Department",
        entity_id=department.id,
        metadata={"name": department.name},
    )
    db.commit()
    db.refresh(department)
    return department


def set_department_active(db: Session, actor: User, department_id: int, active: bool) -> Department:
    department = get_department(db, department_id)
    department.active = active
    record_audit_event(
        db,
        actor_id=actor.id,
        actor_role=actor.role.value,
        action="department_activated" if active else "department_deactivated",
        entity_type="Department",
        entity_id=department.id,
        metadata={},
    )
    db.commit()
    db.refresh(department)
    return department


def list_doctors(db: Session, *, department_id: int | None = None, active_only: bool = True) -> list[Doctor]:
    query = db.query(Doctor)
    if department_id is not None:
        query = query.filter_by(department_id=department_id)
    if active_only:
        query = query.filter_by(active=True)
    return query.order_by(Doctor.name).all()


def get_doctor(db: Session, doctor_id: int) -> Doctor:
    doctor = db.get(Doctor, doctor_id)
    if doctor is None:
        raise DepartmentNotFoundError(f"Doctor {doctor_id} not found")
    return doctor


def create_doctor(db: Session, actor: User, payload) -> Doctor:
    department = get_department(db, payload.department_id)
    if not department.active:
        raise DepartmentInactiveError(f"Department '{department.name}' is not active")

    doctor = Doctor(department_id=department.id, name=payload.name, active=True)
    db.add(doctor)
    db.flush()

    record_audit_event(
        db,
        actor_id=actor.id,
        actor_role=actor.role.value,
        action="doctor_created",
        entity_type="Doctor",
        entity_id=doctor.id,
        metadata={"name": doctor.name, "department_id": department.id},
    )
    db.commit()
    db.refresh(doctor)
    return doctor
