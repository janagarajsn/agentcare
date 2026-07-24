from google.adk.agents import Agent
from google.adk.tools import ToolContext
from sqlalchemy.orm import Session

from app.agents.model_config import get_agent_model
from app.agents.state_keys import ROUTING_RESULT
from app.tools.department_tool import lookup_department

ROUTING_INSTRUCTION = """You are the Department Routing reviewer for a
hospital administrative assistant. You classify requests ADMINISTRATIVELY —
you never use diagnostic language ("this sounds like X condition"), only
department names ("cardiology follow-up request", "dermatology consultation").

Patient's request:
---
{request_text}
---

Identify the single most relevant hospital department implied by this
request (e.g. "Cardiology", "Orthopedics", "Dermatology", "General
Medicine", "Pediatrics", "ENT") and call resolve_department with that
department name. If the request does not clearly imply any department,
call resolve_department with your best guess anyway — the tool will report
back if it's not found, ambiguous, or inactive, and that will be escalated
for human review.
"""


def _build_resolve_department_tool(db: Session):
    def resolve_department(department_query: str, tool_context: ToolContext) -> dict:
        """Look up a hospital department by name against real records.

        Args:
            department_query: The department name or phrase to resolve
                (e.g. "cardiology", "skin care").
        """
        result = lookup_department(db, department_query)
        tool_context.state[ROUTING_RESULT] = result
        return result

    return resolve_department


def build_routing_agent(db: Session) -> Agent:
    return Agent(
        name="routing_agent",
        model=get_agent_model(),
        description="Classifies a request administratively and resolves it to a real hospital department.",
        instruction=ROUTING_INSTRUCTION,
        tools=[_build_resolve_department_tool(db)],
    )
