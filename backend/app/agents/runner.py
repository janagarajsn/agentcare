import uuid

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

APP_NAME = "agentcare"


class AgentTurnResult:
    def __init__(self, final_text: str, state: dict):
        self.final_text = final_text
        self.state = state


class AgentInvoker:
    """Wraps ADK's Runner + a fresh InMemorySessionService per call to run a
    single agent turn and surface the resulting session.state.

    This is the LLM-call boundary the pipeline depends on — tests substitute
    a fake implementation here (see tests/test_workflow_pipeline.py) so the
    suite runs deterministically without real model credentials.
    """

    async def run(self, agent, *, initial_state: dict, message: str) -> AgentTurnResult:
        session_service = InMemorySessionService()
        user_id = "workflow"
        session_id = uuid.uuid4().hex
        await session_service.create_session(
            app_name=APP_NAME, user_id=user_id, session_id=session_id, state=initial_state
        )
        runner = Runner(agent=agent, app_name=APP_NAME, session_service=session_service)

        final_text = ""
        async for event in runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=types.Content(role="user", parts=[types.Part.from_text(text=message)]),
        ):
            if event.is_final_response() and event.content and event.content.parts:
                final_text = "".join(part.text or "" for part in event.content.parts if part.text)

        session = await session_service.get_session(app_name=APP_NAME, user_id=user_id, session_id=session_id)
        return AgentTurnResult(final_text=final_text, state=dict(session.state) if session else initial_state)


default_agent_invoker = AgentInvoker()
