from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.agents.pipeline import run_agentic_workflow
from app.agents.runner import AgentInvoker, default_agent_invoker
from app.auth.rbac import get_current_patient_profile, get_current_user
from app.config import get_settings
from app.db.models import PatientProfile, User, UserRole
from app.db.session import get_db
from app.schemas.appointment import AppointmentOut
from app.schemas.document import PatientDocumentOut
from app.schemas.escalation import EscalationOut
from app.schemas.reminder import ReminderOut
from app.schemas.workflow import SubmitRequestResponse, WorkflowRunOut
from app.services.appointment_service import AppointmentNotFoundError, get_appointment
from app.services.document_service import DocumentNotFoundError, get_document
from app.services.escalation_service import EscalationNotFoundError, get_escalation
from app.services.reminder_service import ReminderNotFoundError, get_reminder
from app.services.workflow_service import (
    WorkflowRunNotFoundError,
    get_workflow_run,
    list_workflow_runs,
)

router = APIRouter(prefix="/workflows", tags=["workflows"])


def get_agent_invoker() -> AgentInvoker:
    return default_agent_invoker


@router.get("", response_model=list[WorkflowRunOut])
def list_workflows(
    patient_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role == UserRole.PATIENT:
        profile = get_current_patient_profile(current_user=current_user, db=db)
        return list_workflow_runs(db, patient_id=profile.id)
    return list_workflow_runs(db, patient_id=patient_id)


@router.post("/submit", response_model=SubmitRequestResponse, status_code=status.HTTP_201_CREATED)
async def submit_request(
    request_text: str = Form(..., min_length=1, max_length=2000),
    files: list[UploadFile] = File(default=[]),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    patient: PatientProfile = Depends(get_current_patient_profile),
    agent_invoker: AgentInvoker = Depends(get_agent_invoker),
) -> SubmitRequestResponse:
    settings = get_settings()
    max_bytes = settings.max_upload_size_mb * 1024 * 1024

    pending_documents: dict[str, tuple[bytes, str]] = {}
    for upload in files:
        content = await upload.read()
        if len(content) > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File '{upload.filename}' exceeds the {settings.max_upload_size_mb}MB upload limit",
            )
        filename = upload.filename or f"upload_{len(pending_documents)}"
        pending_documents[filename] = (content, upload.content_type or "application/octet-stream")

    workflow_run = await run_agentic_workflow(
        db,
        current_user,
        patient,
        request_text,
        pending_documents=pending_documents,
        agent_invoker=agent_invoker,
    )

    return _build_submission_response(db, workflow_run)


@router.get("/{workflow_run_id}", response_model=WorkflowRunOut)
def get_workflow(
    workflow_run_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        run = get_workflow_run(db, workflow_run_id)
    except WorkflowRunNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    if current_user.role == UserRole.PATIENT:
        profile = get_current_patient_profile(current_user=current_user, db=db)
        if run.patient_id != profile.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your workflow run")

    return run


def _build_submission_response(db: Session, workflow_run) -> SubmitRequestResponse:
    state = workflow_run.state or {}

    appointment = None
    appointment_id = (state.get("appointment_result") or {}).get("appointment_id")
    if appointment_id is not None:
        try:
            appointment = get_appointment(db, appointment_id)
        except AppointmentNotFoundError:
            appointment = None

    documents = []
    for doc_result in (state.get("document_result") or {}).get("documents", []):
        if doc_result.get("status") == "stored":
            try:
                documents.append(get_document(db, doc_result["document_id"]))
            except DocumentNotFoundError:
                continue

    reminders = []
    followup_result = state.get("followup_result") or {}
    for key in ("reminder_id", "followup_task_id"):
        reminder_id = followup_result.get(key)
        if reminder_id is not None:
            try:
                reminders.append(get_reminder(db, reminder_id))
            except ReminderNotFoundError:
                continue

    escalation = None
    escalation_id = (state.get("escalation") or {}).get("escalation_id")
    if escalation_id is not None:
        try:
            escalation = get_escalation(db, escalation_id)
        except EscalationNotFoundError:
            escalation = None

    return SubmitRequestResponse(
        workflow_run=WorkflowRunOut.model_validate(workflow_run),
        appointment=AppointmentOut.model_validate(appointment) if appointment else None,
        documents=[PatientDocumentOut.model_validate(d) for d in documents],
        reminders=[ReminderOut.model_validate(r) for r in reminders],
        escalation=EscalationOut.model_validate(escalation) if escalation else None,
    )
