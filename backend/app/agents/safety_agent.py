from google.adk.agents import Agent
from google.adk.tools import ToolContext
from sqlalchemy.orm import Session

from app.agents.model_config import get_agent_model
from app.db.models import EscalationReason
from app.tools.escalation_tool import raise_escalation

_VALID_CATEGORIES = {r.value for r in EscalationReason}

SAFETY_INSTRUCTION = """You are the Safety & Escalation reviewer for a hospital
ADMINISTRATIVE assistant. You never diagnose, prescribe, or give medical advice
yourself — your only job is to judge whether the text you are given requires
escalation to a human before any further administrative action is taken.

Text to review:
---
{safety_review_input}
---

Flag as unsafe (is_unsafe=true) if the text:
- describes a medical emergency (e.g. chest pain, difficulty breathing,
  severe bleeding, suicidal ideation, unconsciousness), OR
- asks the system to diagnose a condition, interpret symptoms medically,
  prescribe medication, or change/recommend a dosage.

Do NOT flag routine administrative language (booking, rescheduling,
department names, document names, dates) even if it mentions a body part or
a department like "cardiology" — naming a department is administrative
routing, not a diagnosis.

You MUST call record_safety_verdict exactly once with your judgment. Set
category to "emergency_language" for emergencies, or
"diagnosis_or_prescription_request" for diagnosis/prescription/dosage asks,
or "none" if the text is safe. Always include a short reason.
"""


def _build_record_verdict_tool(db: Session, workflow_run_id: int, state_key: str):
    def record_safety_verdict(is_unsafe: bool, category: str, reason: str, tool_context: ToolContext) -> dict:
        """Record this reviewer's safety judgment and, if unsafe, raise a
        human-review escalation tied to the current workflow.

        Args:
            is_unsafe: Whether the reviewed text requires human escalation.
            category: One of "emergency_language",
                "diagnosis_or_prescription_request", or "none".
            reason: A short explanation for the judgment.
        """
        result: dict = {"is_unsafe": is_unsafe, "category": category, "reason": reason}

        if is_unsafe:
            escalation_reason = (
                EscalationReason(category) if category in _VALID_CATEGORIES else EscalationReason.OTHER
            )
            escalation_result = raise_escalation(
                db,
                workflow_run_id=workflow_run_id,
                reason=escalation_reason,
                detail=reason,
                actor_role="safety_agent",
            )
            result["escalation"] = escalation_result

        tool_context.state[state_key] = result
        return result

    return record_safety_verdict


def build_safety_agent(db: Session, workflow_run_id: int, state_key: str) -> Agent:
    """Factory (not a module-level singleton) so a fresh agent+closure is
    built per request, per ADK's guidance to avoid 'agent already has a
    parent' errors across concurrent requests."""
    return Agent(
        name="safety_agent",
        model=get_agent_model(),
        description="Reviews text for medical emergencies or diagnosis/prescription requests and escalates to a human when needed.",
        instruction=SAFETY_INSTRUCTION,
        tools=[_build_record_verdict_tool(db, workflow_run_id, state_key)],
    )
