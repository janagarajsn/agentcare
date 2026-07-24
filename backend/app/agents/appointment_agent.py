from datetime import datetime

from google.adk.agents import Agent
from google.adk.tools import ToolContext
from sqlalchemy.orm import Session

from app.agents.model_config import get_agent_model
from app.agents.state_keys import APPOINTMENT_RESULT
from app.db.models import PatientProfile, User
from app.tools.appointment_tool import (
    list_my_active_appointments as _list_my_active_appointments,
    try_book_appointment,
    try_cancel_appointment,
    try_reschedule_appointment,
)
from app.tools.slot_tool import find_available_slots

APPOINTMENT_INSTRUCTION = """You are the Appointment reviewer for a hospital
administrative assistant. You never diagnose or give medical advice — you
only manage scheduling.

Patient's request:
---
{request_text}
---

Department routing result (use department_id from here if present — but
note routing may be irrelevant for a reschedule/cancel of an EXISTING
appointment, since that appointment's department is already fixed):
{routing_result}

Decide what the request is actually asking for:

A) Booking a NEW appointment — the department was just resolved and there
   is no existing appointment being referenced.
   1. If the department was not found or is ambiguous/inactive, do not
      attempt to book — report that back, call no tool.
   2. Otherwise call find_slots with the resolved department_id (narrow
      with start_after/start_before as ISO 8601 datetimes if a date range
      is implied, e.g. "next week"; omit them otherwise).
   3. Pick the earliest suitable open slot from the tool's real results and
      call book_slot with its slot_id. Never invent a slot_id that wasn't
      returned by find_slots.

B) Rescheduling or cancelling an EXISTING appointment ("my appointment",
   "postpone it", "move my visit", etc.) — this does NOT require a
   resolved department.
   1. Call list_my_active_appointments to see the patient's real upcoming
      appointments (id, doctor, department, current time, status). Never
      invent an appointment_id — only use one returned by this tool.
   2. If exactly one active appointment matches what the patient is
      describing (or they only have one active appointment at all), that's
      the target.
   3. If there are multiple and it's genuinely unclear which one they mean
      (e.g. two active appointments and nothing in the request narrows it
      down), do not guess — report that back and call no booking tool.
   4. For a reschedule: call find_slots for that appointment's department_id
      to get real open slots, then call reschedule_appointment with the
      target appointment_id and a new_slot_id chosen from those results.
   5. For a cancellation: call cancel_appointment with the target
      appointment_id.

If no open slots match, or a tool reports a conflict/not-found, report that
back plainly — do not claim an action succeeded when it did not.
"""


def _build_find_slots_tool(db: Session):
    def find_slots(department_id: int, start_after: str, start_before: str, tool_context: ToolContext) -> dict:
        """Find real open appointment slots for a department.

        Args:
            department_id: The resolved department id to search within.
            start_after: ISO 8601 datetime lower bound, or empty string for no bound.
            start_before: ISO 8601 datetime upper bound, or empty string for no bound.
        """
        after = _parse_iso(start_after)
        before = _parse_iso(start_before)
        return find_available_slots(db, department_id=department_id, start_after=after, start_before=before)

    return find_slots


def _parse_iso(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _build_book_slot_tool(db: Session, patient: PatientProfile):
    def book_slot(slot_id: int, reason: str, tool_context: ToolContext) -> dict:
        """Book a real appointment slot for the current patient.

        Args:
            slot_id: The id of an OPEN slot returned by find_slots.
            reason: A short administrative reason for the visit.
        """
        result = try_book_appointment(db, patient, slot_id, reason)
        tool_context.state[APPOINTMENT_RESULT] = result
        return result

    return book_slot


def _build_reschedule_tool(db: Session, patient: PatientProfile):
    def reschedule_appointment(appointment_id: int, new_slot_id: int, tool_context: ToolContext) -> dict:
        """Reschedule an existing appointment owned by the current patient
        to a different open slot.

        Args:
            appointment_id: The existing appointment's id.
            new_slot_id: The id of an OPEN slot returned by find_slots.
        """
        result = try_reschedule_appointment(db, patient, appointment_id, new_slot_id)
        tool_context.state[APPOINTMENT_RESULT] = result
        return result

    return reschedule_appointment


def _build_list_my_appointments_tool(db: Session, patient: PatientProfile):
    def list_my_active_appointments(tool_context: ToolContext) -> dict:
        """List the current patient's own active (pending/confirmed/
        rescheduled) appointments — use this to resolve "my appointment"
        style requests to a real appointment_id before rescheduling or
        cancelling."""
        return _list_my_active_appointments(db, patient)

    return list_my_active_appointments


def _build_cancel_tool(db: Session, user: User, patient: PatientProfile):
    def cancel_appointment(appointment_id: int, tool_context: ToolContext) -> dict:
        """Cancel an existing appointment owned by the current patient.

        Args:
            appointment_id: The existing appointment's id.
        """
        result = try_cancel_appointment(db, user, appointment_id, patient)
        tool_context.state[APPOINTMENT_RESULT] = result
        return result

    return cancel_appointment


def build_appointment_agent(db: Session, user: User, patient: PatientProfile) -> Agent:
    return Agent(
        name="appointment_agent",
        model=get_agent_model(),
        description="Finds real availability and books/reschedules/cancels appointments, with conflict checking.",
        instruction=APPOINTMENT_INSTRUCTION,
        tools=[
            _build_list_my_appointments_tool(db, patient),
            _build_find_slots_tool(db),
            _build_book_slot_tool(db, patient),
            _build_reschedule_tool(db, patient),
            _build_cancel_tool(db, user, patient),
        ],
    )
