import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class WorkflowStatus(str, enum.Enum):
    RUNNING = "running"
    AWAITING_ESCALATION = "awaiting_escalation"
    COMPLETED = "completed"
    FAILED = "failed"
    STALLED = "stalled"


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patient_profiles.id"), nullable=False)
    current_step: Mapped[str] = mapped_column(String(64), nullable=False, default="intake")
    state: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[WorkflowStatus] = mapped_column(
        Enum(WorkflowStatus), default=WorkflowStatus.RUNNING, nullable=False
    )
    request_text: Mapped[str] = mapped_column(String(2000), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    patient: Mapped["PatientProfile"] = relationship()
    escalations: Mapped[list["Escalation"]] = relationship(back_populates="workflow_run")
