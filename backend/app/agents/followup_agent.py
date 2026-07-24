from datetime import timedelta

from google.adk.agents import Agent
from google.adk.tools import ToolContext
from sqlalchemy.orm import Session

from app.agents.model_config import get_agent_model
from app.agents.state_keys import FOLLOWUP_RESULT
from app.db.models import Appointment, PatientProfile, ReminderType, User
from app.services.reminder_service import AppointmentOwnershipError, upsert_appointment_reminder

FOLLOWUP_INSTRUCTION = """You are the Follow-up reviewer for a hospital
administrative assistant. You only schedule reminders and follow-up tasks —
you never give medical advice.

Appointment outcome from this request (may be empty if none):
{appointment_result}

If appointment_result shows a real appointment_id with status "booked" or
"rescheduled", call schedule_appointment_followups with that appointment_id
exactly once to create a pre-visit reminder and a post-visit follow-up
task. Otherwise, do not call any tool — there is nothing to follow up on
yet.
"""


def _build_schedule_followups_tool(db: Session, user: User, patient: PatientProfile):
    def schedule_appointment_followups(appointment_id: int, tool_context: ToolContext) -> dict:
        """Create a pre-visit reminder and a post-visit follow-up task for a
        real, just-booked appointment.

        Args:
            appointment_id: The id of the booked/rescheduled appointment.
        """
        appointment = db.get(Appointment, appointment_id)
        if appointment is None or appointment.patient_id != patient.id:
            result = {"status": "appointment_not_found"}
            tool_context.state[FOLLOWUP_RESULT] = result
            return result

        slot = appointment.slot
        try:
            reminder = upsert_appointment_reminder(
                db,
                actor_id=user.id,
                actor_role=user.role.value,
                patient=patient,
                reminder_type=ReminderType.APPOINTMENT_REMINDER,
                scheduled_at=slot.start_time - timedelta(days=1),
                appointment_id=appointment.id,
            )
            followup_task = upsert_appointment_reminder(
                db,
                actor_id=user.id,
                actor_role=user.role.value,
                patient=patient,
                reminder_type=ReminderType.POST_VISIT_FOLLOWUP,
                scheduled_at=slot.end_time + timedelta(days=1),
                appointment_id=appointment.id,
            )
        except AppointmentOwnershipError as exc:
            result = {"status": "error", "detail": str(exc)}
            tool_context.state[FOLLOWUP_RESULT] = result
            return result

        result = {
            "status": "scheduled",
            "reminder_id": reminder.id,
            "followup_task_id": followup_task.id,
        }
        tool_context.state[FOLLOWUP_RESULT] = result
        return result

    return schedule_appointment_followups


def build_followup_agent(db: Session, user: User, patient: PatientProfile) -> Agent:
    return Agent(
        name="followup_agent",
        model=get_agent_model(),
        description="Schedules appointment reminders and post-visit follow-up tasks from real booking outcomes.",
        instruction=FOLLOWUP_INSTRUCTION,
        tools=[_build_schedule_followups_tool(db, user, patient)],
    )
