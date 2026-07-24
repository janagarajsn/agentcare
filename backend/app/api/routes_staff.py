from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.rbac import require_role
from app.db.models import AuditEvent, User, UserRole
from app.db.session import get_db
from app.schemas.appointment import SlotCreateRequest, SlotOut
from app.schemas.audit import AuditEventOut
from app.schemas.auth import StaffCreateRequest
from app.schemas.department import (
    DepartmentCreateRequest,
    DepartmentOut,
    DoctorCreateRequest,
    DoctorOut,
)
from app.schemas.user import UserOut
from app.services.auth_service import EmailAlreadyRegisteredError, create_staff_user
from app.services.department_service import (
    DepartmentInactiveError,
    DepartmentNotFoundError,
    DuplicateDepartmentError,
    create_department,
    create_doctor,
    list_departments,
    list_doctors,
    set_department_active,
)
from app.services.slot_service import (
    DoctorNotFoundError,
    SlotOverlapError,
    create_slot,
    list_available_slots,
)

router = APIRouter(prefix="/staff", tags=["staff"])


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_staff_account(
    payload: StaffCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
) -> User:
    try:
        return create_staff_user(db, current_user, payload)
    except (EmailAlreadyRegisteredError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/departments", response_model=list[DepartmentOut])
def list_departments_route(
    active_only: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.STAFF, UserRole.ADMIN)),
):
    return list_departments(db, active_only=active_only)


@router.post("/departments", response_model=DepartmentOut, status_code=status.HTTP_201_CREATED)
def create_department_route(
    payload: DepartmentCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    try:
        return create_department(db, current_user, payload)
    except DuplicateDepartmentError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.patch("/departments/{department_id}/active", response_model=DepartmentOut)
def set_department_active_route(
    department_id: int,
    active: bool,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    try:
        return set_department_active(db, current_user, department_id, active)
    except DepartmentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/doctors", response_model=list[DoctorOut])
def list_doctors_route(
    department_id: int | None = None,
    active_only: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.STAFF, UserRole.ADMIN)),
):
    return list_doctors(db, department_id=department_id, active_only=active_only)


@router.post("/doctors", response_model=DoctorOut, status_code=status.HTTP_201_CREATED)
def create_doctor_route(
    payload: DoctorCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    try:
        return create_doctor(db, current_user, payload)
    except DepartmentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except DepartmentInactiveError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/slots", response_model=list[SlotOut])
def list_slots_route(
    doctor_id: int | None = None,
    department_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.STAFF, UserRole.ADMIN)),
):
    return list_available_slots(db, department_id=department_id, doctor_id=doctor_id)


@router.post("/slots", response_model=SlotOut, status_code=status.HTTP_201_CREATED)
def create_slot_route(
    payload: SlotCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.STAFF, UserRole.ADMIN)),
):
    try:
        return create_slot(db, current_user, payload.doctor_id, payload.start_time, payload.end_time)
    except DoctorNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SlotOverlapError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/audit-events", response_model=list[AuditEventOut])
def list_audit_events_route(
    entity_type: str | None = None,
    limit: int = 200,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.STAFF, UserRole.ADMIN)),
):
    query = db.query(AuditEvent)
    if entity_type is not None:
        query = query.filter_by(entity_type=entity_type)
    return query.order_by(AuditEvent.created_at.desc()).limit(min(limit, 1000)).all()
