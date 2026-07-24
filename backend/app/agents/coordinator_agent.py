from google.adk.agents import Agent
from google.adk.tools import ToolContext
from sqlalchemy.orm import Session

from app.agents.model_config import get_agent_model
from app.agents.state_keys import PATIENT_RESULT, PLAN
from app.db.models import User
from app.tools.patient_tool import find_or_create_patient_profile

COORDINATOR_INSTRUCTION = """You are the Coordinator for a hospital
administrative assistant. You do not handle medical questions yourself.

Patient's request:
---
{request_text}
---

Do the following, in order:
1. Call resolve_patient to confirm the patient record for this session.
2. Decide which downstream steps are actually needed for this specific
   request, then call record_plan exactly once:
   - needs_routing: true if the request needs a department to be
     identified (new appointment, follow-up, transfer).
   - needs_appointment: true if the request wants to book, reschedule, or
     cancel an appointment.
   - needs_document_check: true if the request mentions attaching,
     uploading, or checking documents/reports/scans, OR if there are
     pending uploaded files for this request: {pending_filenames}
   - needs_followup: true if an appointment is being booked or rescheduled
     (reminders should follow), or the request explicitly asks about
     reminders/follow-ups.
   - is_administrative_only: true only if the request has no routing,
     appointment, or document component at all (e.g. a general status
     question).
   A request can need more than one step. A document-only message (e.g.
   "please attach my new ECG to my existing appointment") should usually
   have needs_routing=false and needs_appointment=false.
"""


def _build_resolve_patient_tool(db: Session, user: User):
    def resolve_patient(tool_context: ToolContext) -> dict:
        """Confirm the PatientProfile backing this session exists."""
        result = find_or_create_patient_profile(db, user)
        tool_context.state[PATIENT_RESULT] = result
        return result

    return resolve_patient


def _build_record_plan_tool():
    def record_plan(
        needs_routing: bool,
        needs_appointment: bool,
        needs_document_check: bool,
        needs_followup: bool,
        is_administrative_only: bool,
        tool_context: ToolContext,
    ) -> dict:
        """Record which downstream steps this request actually needs.

        Args:
            needs_routing: Whether department routing is needed.
            needs_appointment: Whether appointment booking/reschedule/cancel is needed.
            needs_document_check: Whether document classification/coordination is needed.
            needs_followup: Whether a reminder or follow-up task should be created.
            is_administrative_only: Whether none of the above apply.
        """
        plan = {
            "needs_routing": needs_routing,
            "needs_appointment": needs_appointment,
            "needs_document_check": needs_document_check,
            "needs_followup": needs_followup,
            "is_administrative_only": is_administrative_only,
        }
        tool_context.state[PLAN] = plan
        return plan

    return record_plan


def build_coordinator_agent(db: Session, user: User) -> Agent:
    return Agent(
        name="coordinator_agent",
        model=get_agent_model(),
        description="Resolves patient identity and decides which specialized agents this request actually needs.",
        instruction=COORDINATOR_INSTRUCTION,
        tools=[_build_resolve_patient_tool(db, user), _build_record_plan_tool()],
    )
