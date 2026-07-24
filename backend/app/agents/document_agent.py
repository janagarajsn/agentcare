from google.adk.agents import Agent
from google.adk.tools import ToolContext
from sqlalchemy.orm import Session

from app.agents.model_config import get_agent_model
from app.agents.state_keys import DOCUMENT_RESULT
from app.db.models import PatientProfile
from app.services.document_service import classify_by_filename
from app.tools.document_tool import classify_and_store_document, find_missing_documents_by_department

DOCUMENT_INSTRUCTION = """You are the Document Coordination reviewer for a
hospital administrative assistant. You classify and file documents — you
never interpret their medical content.

Patient's request:
---
{request_text}
---

Department routing result (use department_name from here if present):
{routing_result}

Files attached to this request (may be empty): {pending_filenames}

1. For every filename listed above, call store_pending_document with that
   exact filename so it gets classified, checksummed, and filed for real.
2. If a department was resolved, call check_missing_documents for that
   department to see which required document types are still missing for
   this patient, using its real, current records.
3. If there are no attached files and no resolved department, there is
   nothing to do — do not call any tool.
"""


def _build_store_pending_tool(db: Session, patient: PatientProfile, pending_documents: dict):
    def store_pending_document(filename: str, tool_context: ToolContext) -> dict:
        """Classify and store one of the files attached to this request.

        Args:
            filename: The exact filename from the attached-files list.
        """
        pending = pending_documents.get(filename)
        if pending is None:
            return {"status": "not_found", "detail": f"No pending file named '{filename}'"}

        content, content_type = pending
        document_type = classify_by_filename(filename)
        result = classify_and_store_document(
            db,
            patient,
            content=content,
            content_type=content_type,
            original_filename=filename,
            document_type=document_type,
            document_date=None,
            appointment_id=None,
        )
        tool_context.state.setdefault(DOCUMENT_RESULT, {})
        documents_so_far = tool_context.state[DOCUMENT_RESULT].get("documents", [])
        documents_so_far.append(result)
        tool_context.state[DOCUMENT_RESULT] = {**tool_context.state[DOCUMENT_RESULT], "documents": documents_so_far}
        return result

    return store_pending_document


def _build_check_missing_tool(db: Session, patient: PatientProfile):
    def check_missing_documents(department_name: str, tool_context: ToolContext) -> dict:
        """Check which required document types are still missing for this
        patient in the given department, against real stored records.

        Args:
            department_name: The resolved department name.
        """
        result = find_missing_documents_by_department(db, patient.id, department_name)
        existing = tool_context.state.get(DOCUMENT_RESULT, {})
        tool_context.state[DOCUMENT_RESULT] = {**existing, "missing_check": result}
        return result

    return check_missing_documents


def build_document_agent(db: Session, patient: PatientProfile, pending_documents: dict) -> Agent:
    return Agent(
        name="document_agent",
        model=get_agent_model(),
        description="Classifies and files attached documents and checks for missing required documents.",
        instruction=DOCUMENT_INSTRUCTION,
        tools=[
            _build_store_pending_tool(db, patient, pending_documents),
            _build_check_missing_tool(db, patient),
        ],
    )
