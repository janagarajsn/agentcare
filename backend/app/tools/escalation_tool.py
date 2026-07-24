from sqlalchemy.orm import Session

from app.db.models import EscalationReason, User
from app.services.escalation_service import (
    EscalationAlreadyResolvedError,
    EscalationNotFoundError,
    create_escalation,
    resolve_escalation,
)
from app.services.workflow_service import WorkflowRunNotFoundError


def raise_escalation(
    db: Session,
    *,
    workflow_run_id: int,
    reason: EscalationReason,
    detail: str | None = None,
    actor_id: int | None = None,
    actor_role: str = "system",
) -> dict:
    try:
        escalation = create_escalation(
            db,
            workflow_run_id=workflow_run_id,
            reason=reason,
            detail=detail,
            actor_id=actor_id,
            actor_role=actor_role,
        )
    except WorkflowRunNotFoundError as exc:
        return {"status": "workflow_not_found", "detail": str(exc)}

    return {"status": "escalated", "escalation_id": escalation.id}


def resolve(db: Session, reviewer: User, escalation_id: int, decision: str, note: str | None) -> dict:
    try:
        escalation = resolve_escalation(db, reviewer, escalation_id, decision, note)
    except EscalationNotFoundError as exc:
        return {"status": "not_found", "detail": str(exc)}
    except EscalationAlreadyResolvedError as exc:
        return {"status": "already_resolved", "detail": str(exc)}

    return {"status": "resolved", "escalation_id": escalation.id, "decision": decision}
