"""Test double for the ADK LLM-call boundary (app.agents.runner.AgentInvoker).

Real tool closures (real DB/service logic) are still invoked — only the
*decision* of which tool to call, with what arguments, is scripted here
instead of coming from an actual model call. This lets the pipeline tests
exercise genuine end-to-end tool wiring deterministically and without any
real API credentials, per the project's testing requirements.
"""

from types import SimpleNamespace

from app.agents.runner import AgentInvoker, AgentTurnResult


class FakeAgentInvoker(AgentInvoker):
    def __init__(self, script: dict):
        # script: {agent_name: callable(state: dict, message: str, call_tool: callable) -> None}
        self.script = script
        self.invocations: list[str] = []

    async def run(self, agent, *, initial_state: dict, message: str) -> AgentTurnResult:
        self.invocations.append(agent.name)
        state = dict(initial_state)
        tool_context = SimpleNamespace(state=state)
        tools_by_name = {tool.__name__: tool for tool in agent.tools}

        def call_tool(name: str, **kwargs):
            return tools_by_name[name](**kwargs, tool_context=tool_context)

        handler = self.script.get(agent.name)
        if handler is not None:
            handler(state, message, call_tool)

        return AgentTurnResult(final_text=f"(fake response from {agent.name})", state=state)


class AlwaysFailingAgentInvoker(AgentInvoker):
    """Simulates a persistently unavailable model (e.g. network/API outage)
    to exercise the retry-then-fail-gracefully path."""

    def __init__(self):
        self.attempts = 0

    async def run(self, agent, *, initial_state: dict, message: str) -> AgentTurnResult:
        self.attempts += 1
        raise RuntimeError("simulated model call failure")
