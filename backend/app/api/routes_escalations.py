from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.rbac import require_role
from app.db.models import EscalationStatus, User, UserRole
from app.db.session import get_db
from app.schemas.escalation import EscalationOut, EscalationResolveRequest
from app.services.escalation_service import (
    EscalationNotFoundError,
    get_escalation,
    list_escalations,
)
from app.tools.escalation_tool import resolve

router = APIRouter(prefix="/escalations", tags=["escalations"])


@router.get("", response_model=list[EscalationOut])
def list_escalations_route(
    status_filter: EscalationStatus | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.STAFF, UserRole.ADMIN)),
):
    return list_escalations(db, status=status_filter)


@router.get("/{escalation_id}", response_model=EscalationOut)
def get_escalation_route(
    escalation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.STAFF, UserRole.ADMIN)),
):
    try:
        return get_escalation(db, escalation_id)
    except EscalationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{escalation_id}/resolve", response_model=EscalationOut)
def resolve_escalation_route(
    escalation_id: int,
    payload: EscalationResolveRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.STAFF, UserRole.ADMIN)),
):
    result = resolve(db, current_user, escalation_id, payload.decision, payload.note)
    if result["status"] == "not_found":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=result["detail"])
    if result["status"] != "resolved":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=result["detail"])
    return get_escalation(db, escalation_id)
