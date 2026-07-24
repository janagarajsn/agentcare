from sqlalchemy.orm import Session

from app.db.models import AuditEvent


def record_audit_event(
    db: Session,
    *,
    actor_id: int | None,
    actor_role: str,
    action: str,
    entity_type: str,
    entity_id: int | None = None,
    metadata: dict | None = None,
) -> AuditEvent:
    """Append an audit trail row. Part of the caller's transaction — the
    caller is responsible for db.commit(); this only adds and flushes so the
    generated id is available immediately."""
    event = AuditEvent(
        actor_id=actor_id,
        actor_role=actor_role,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        event_metadata=metadata or {},
    )
    db.add(event)
    db.flush()
    return event
