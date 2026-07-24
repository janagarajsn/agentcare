import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class EscalationReason(str, enum.Enum):
    EMERGENCY_LANGUAGE = "emergency_language"
    DIAGNOSIS_OR_PRESCRIPTION_REQUEST = "diagnosis_or_prescription_request"
    AMBIGUOUS_ROUTING = "ambiguous_routing"
    UNSUPPORTED_DEPARTMENT = "unsupported_department"
    APPOINTMENT_CONFLICT_UNRESOLVED = "appointment_conflict_unresolved"
    SENSITIVE_DOCUMENT = "sensitive_document"
    OTHER = "other"


class EscalationStatus(str, enum.Enum):
    OPEN = "open"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    RESOLVED = "resolved"


class Escalation(Base):
    __tablename__ = "escalations"

    id: Mapped[int] = mapped_column(primary_key=True)
    workflow_run_id: Mapped[int] = mapped_column(ForeignKey("workflow_runs.id"), nullable=False)
    reason: Mapped[EscalationReason] = mapped_column(Enum(EscalationReason), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[EscalationStatus] = mapped_column(
        Enum(EscalationStatus), default=EscalationStatus.OPEN, nullable=False
    )
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    workflow_run: Mapped["WorkflowRun"] = relationship(back_populates="escalations")
