import enum
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class DocumentType(str, enum.Enum):
    ECG = "ecg"
    BLOOD_REPORT = "blood_report"
    IMAGING = "imaging"
    PRESCRIPTION_HISTORY = "prescription_history"
    DISCHARGE_SUMMARY = "discharge_summary"
    IDENTITY_PROOF = "identity_proof"
    INSURANCE_CARD = "insurance_card"
    REFERRAL_LETTER = "referral_letter"
    OTHER = "other"


class PatientDocument(Base):
    __tablename__ = "patient_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patient_profiles.id"), nullable=False)
    appointment_id: Mapped[int | None] = mapped_column(ForeignKey("appointments.id"), nullable=True)
    document_type: Mapped[DocumentType] = mapped_column(Enum(DocumentType), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(512), nullable=False)
    document_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    is_duplicate: Mapped[bool] = mapped_column(default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    patient: Mapped["PatientProfile"] = relationship()
    appointment: Mapped["Appointment | None"] = relationship(back_populates="documents")
