from datetime import datetime

from sqlalchemy.orm import Session

from app.db.models import Escalation, EscalationReason, EscalationStatus, User, WorkflowStatus
from app.services.workflow_service import get_workflow_run
from app.tools.audit_tool import record_audit_event


class EscalationNotFoundError(Exception):
    pass


class EscalationAlreadyResolvedError(Exception):
    pass


def create_escalation(
    db: Session,
    *,
    workflow_run_id: int,
    reason: EscalationReason,
    detail: str | None,
    actor_id: int | None = None,
    actor_role: str = "system",
) -> Escalation:
    workflow_run = get_workflow_run(db, workflow_run_id)

    escalation = Escalation(
        workflow_run_id=workflow_run.id,
        reason=reason,
        detail=detail,
        status=EscalationStatus.OPEN,
    )
    db.add(escalation)
    workflow_run.status = WorkflowStatus.AWAITING_ESCALATION
    db.flush()

    record_audit_event(
        db,
        actor_id=actor_id,
        actor_role=actor_role,
        action="escalation_created",
        entity_type="Escalation",
        entity_id=escalation.id,
        metadata={"reason": reason.value, "workflow_run_id": workflow_run.id},
    )
    db.commit()
    db.refresh(escalation)
    return escalation


def get_escalation(db: Session, escalation_id: int) -> Escalation:
    escalation = db.get(Escalation, escalation_id)
    if escalation is None:
        raise EscalationNotFoundError(f"Escalation {escalation_id} not found")
    return escalation


def list_escalations(db: Session, *, status: EscalationStatus | None = None) -> list[Escalation]:
    query = db.query(Escalation)
    if status is not None:
        query = query.filter_by(status=status)
    return query.order_by(Escalation.created_at.desc()).all()


def resolve_escalation(
    db: Session, reviewer: User, escalation_id: int, decision: str, note: str | None
) -> Escalation:
    escalation = get_escalation(db, escalation_id)
    if escalation.status not in (EscalationStatus.OPEN, EscalationStatus.IN_REVIEW):
        raise EscalationAlreadyResolvedError(f"Escalation {escalation_id} is already resolved")

    escalation.status = EscalationStatus.APPROVED if decision == "approved" else EscalationStatus.REJECTED
    escalation.reviewed_by = reviewer.id
    escalation.review_note = note
    escalation.resolved_at = datetime.utcnow()

    workflow_run = get_workflow_run(db, escalation.workflow_run_id)
    workflow_run.status = WorkflowStatus.RUNNING if decision == "approved" else WorkflowStatus.FAILED

    record_audit_event(
        db,
        actor_id=reviewer.id,
        actor_role=reviewer.role.value,
        action="escalation_resolved",
        entity_type="Escalation",
        entity_id=escalation.id,
        metadata={"decision": decision, "note": note},
    )
    db.commit()
    db.refresh(escalation)
    return escalation
