import asyncio
import logging

from sqlalchemy.orm import Session

from app.agents.appointment_agent import build_appointment_agent
from app.agents.coordinator_agent import build_coordinator_agent
from app.agents.document_agent import build_document_agent
from app.agents.followup_agent import build_followup_agent
from app.agents.routing_agent import build_routing_agent
from app.agents.runner import AgentInvoker, AgentTurnResult, default_agent_invoker
from app.agents.safety_agent import build_safety_agent
from app.agents.safety_rules import screen_text
from app.agents.state_keys import (
    APPOINTMENT_RESULT,
    DOCUMENT_RESULT,
    FOLLOWUP_RESULT,
    PATIENT_RESULT,
    PLAN,
    ROUTING_RESULT,
    SAFETY_VERDICT_POST,
    SAFETY_VERDICT_PRE,
)
from app.db.models import EscalationReason, PatientDocument, PatientProfile, User, WorkflowRun, WorkflowStatus
from app.services.workflow_service import create_workflow_run, get_workflow_run, update_workflow_state
from app.tools.escalation_tool import raise_escalation

logger = logging.getLogger("agentcare.pipeline")

_DEFAULT_PLAN = {
    "needs_routing": True,
    "needs_appointment": False,
    "needs_document_check": False,
    "needs_followup": False,
    "is_administrative_only": False,
}

_MAX_AGENT_ATTEMPTS = 2
_RETRY_BACKOFF_SECONDS = 0.5


class AgentInvocationError(Exception):
    pass


async def _invoke_with_retry(
    invoker: AgentInvoker, agent, *, initial_state: dict, message: str
) -> AgentTurnResult:
    """Retry-with-backoff around the actual LLM call boundary, so a transient
    model/network failure doesn't crash the whole request — it either
    recovers on retry or surfaces as a handled AgentInvocationError that the
    orchestrator turns into a FAILED (not stuck) WorkflowRun."""
    last_exc: Exception | None = None
    for attempt in range(1, _MAX_AGENT_ATTEMPTS + 1):
        try:
            return await invoker.run(agent, initial_state=initial_state, message=message)
        except Exception as exc:  # noqa: BLE001 - any model/tool failure must be caught here
            last_exc = exc
            logger.warning("Agent '%s' attempt %d/%d failed: %s", agent.name, attempt, _MAX_AGENT_ATTEMPTS, exc)
            if attempt < _MAX_AGENT_ATTEMPTS:
                await asyncio.sleep(_RETRY_BACKOFF_SECONDS * attempt)

    raise AgentInvocationError(f"Agent '{agent.name}' failed after {_MAX_AGENT_ATTEMPTS} attempts") from last_exc


async def run_agentic_workflow(
    db: Session,
    user: User,
    patient: PatientProfile,
    request_text: str,
    pending_documents: dict[str, tuple[bytes, str]] | None = None,
    agent_invoker: AgentInvoker | None = None,
) -> WorkflowRun:
    """The Coordinator's orchestration, made explicit in Python so the
    dispatch/halt decisions are enforced in code rather than left to an
    LLM's cooperation. Persists WorkflowRun.state after every step so the
    run survives a process restart, per the durable-state requirement.
    """
    invoker = agent_invoker or default_agent_invoker
    pending_documents = pending_documents or {}
    pending_filenames = list(pending_documents.keys())

    workflow_run = create_workflow_run(db, patient.id, request_text)

    # 1. Deterministic guardrail — pure Python, runs regardless of LLM health.
    pre_screen = screen_text(request_text)
    if pre_screen["is_unsafe"]:
        _escalate_and_halt(
            db,
            workflow_run.id,
            reason=pre_screen["category"],
            detail=f"Deterministic safety screen matched: '{pre_screen['matched_phrase']}'",
            current_step="safety_pre_check_deterministic",
            extra_state={"safety_pre_screen_deterministic": _jsonable(pre_screen)},
        )
        return get_workflow_run(db, workflow_run.id)

    try:
        return await _run_pipeline_steps(db, invoker, user, patient, workflow_run, request_text, pending_documents, pending_filenames)
    except AgentInvocationError as exc:
        logger.error("Workflow %s failed: %s", workflow_run.id, exc)
        update_workflow_state(
            db,
            workflow_run.id,
            status=WorkflowStatus.FAILED,
            current_step="agent_invocation_failed",
            state_patch={"error": str(exc)},
        )
        return get_workflow_run(db, workflow_run.id)


async def _run_pipeline_steps(
    db: Session,
    invoker: AgentInvoker,
    user: User,
    patient: PatientProfile,
    workflow_run: WorkflowRun,
    request_text: str,
    pending_documents: dict[str, tuple[bytes, str]],
    pending_filenames: list[str],
) -> WorkflowRun:
    # 2. Safety Agent (LLM) — nuance layer on the raw incoming request.
    safety_pre_agent = build_safety_agent(db, workflow_run.id, SAFETY_VERDICT_PRE)
    safety_pre_turn = await _invoke_with_retry(
        invoker, safety_pre_agent, initial_state={"safety_review_input": request_text}, message=request_text
    )
    verdict_pre = safety_pre_turn.state.get(SAFETY_VERDICT_PRE, {"is_unsafe": False})
    update_workflow_state(
        db, workflow_run.id, current_step="safety_check_pre", state_patch={"safety_verdict_pre": verdict_pre}
    )
    if verdict_pre.get("is_unsafe"):
        update_workflow_state(
            db, workflow_run.id, status=WorkflowStatus.AWAITING_ESCALATION, current_step="safety_check_pre"
        )
        return get_workflow_run(db, workflow_run.id)

    # 3. Coordinator — resolves patient identity, decides which steps are needed.
    coordinator_agent = build_coordinator_agent(db, user)
    coordinator_turn = await _invoke_with_retry(
        invoker,
        coordinator_agent,
        initial_state={"request_text": request_text, "pending_filenames": pending_filenames},
        message=request_text,
    )
    plan = coordinator_turn.state.get(PLAN) or {
        **_DEFAULT_PLAN,
        "needs_document_check": bool(pending_documents),
    }
    update_workflow_state(
        db,
        workflow_run.id,
        current_step="coordinator",
        state_patch={"plan": plan, "patient_result": coordinator_turn.state.get(PATIENT_RESULT)},
    )

    # 4. Routing (conditionally).
    routing_state: dict = {}
    if plan.get("needs_routing"):
        routing_agent = build_routing_agent(db)
        routing_turn = await _invoke_with_retry(
            invoker, routing_agent, initial_state={"request_text": request_text}, message=request_text
        )
        routing_state = routing_turn.state.get(ROUTING_RESULT, {"status": "not_found"})
        update_workflow_state(
            db, workflow_run.id, current_step="routing", state_patch={"routing_result": routing_state}
        )

        if routing_state.get("status") in ("not_found", "ambiguous", "inactive"):
            reason = (
                EscalationReason.UNSUPPORTED_DEPARTMENT
                if routing_state.get("status") == "not_found"
                else EscalationReason.AMBIGUOUS_ROUTING
            )
            _escalate_and_halt(
                db,
                workflow_run.id,
                reason=reason,
                detail=f"Routing could not resolve a department: {routing_state}",
                current_step="routing",
            )
            return get_workflow_run(db, workflow_run.id)

    # 5. Appointment + Document run concurrently — both depend only on
    #    routing_state, neither depends on the other's output.
    # Routing is only a hard prerequisite when it was actually attempted
    # (i.e. a NEW booking needing a department resolved). Reschedule/cancel
    # of an EXISTING appointment doesn't need a department at all, so
    # needs_routing is correctly False for those requests — that must not
    # block the Appointment Agent from running.
    routing_ok = (not plan.get("needs_routing")) or routing_state.get("status") == "found"
    needs_appointment = bool(plan.get("needs_appointment")) and routing_ok
    needs_document = bool(plan.get("needs_document_check"))

    async def _run_appointment() -> dict:
        agent = build_appointment_agent(db, user, patient)
        turn = await _invoke_with_retry(
            invoker,
            agent,
            initial_state={"request_text": request_text, "routing_result": routing_state},
            message=request_text,
        )
        return turn.state.get(APPOINTMENT_RESULT, {})

    async def _run_document() -> dict:
        agent = build_document_agent(db, patient, pending_documents)
        turn = await _invoke_with_retry(
            invoker,
            agent,
            initial_state={
                "request_text": request_text,
                "routing_result": routing_state,
                "pending_filenames": pending_filenames,
            },
            message=request_text,
        )
        return turn.state.get(DOCUMENT_RESULT, {})

    appointment_state: dict = {}
    document_state: dict = {}
    coros = {}
    if needs_appointment:
        coros["appointment"] = _run_appointment()
    if needs_document:
        coros["document"] = _run_document()

    if coros:
        results = await asyncio.gather(*coros.values())
        for key, result in zip(coros.keys(), results):
            if key == "appointment":
                appointment_state = result
            else:
                document_state = result

    update_workflow_state(
        db,
        workflow_run.id,
        current_step="appointment_and_document",
        state_patch={"appointment_result": appointment_state, "document_result": document_state},
    )

    # 6. Deterministic linking — attach any newly-stored documents to a
    #    newly-booked appointment. Plain Python, not an LLM decision.
    if appointment_state.get("status") in ("booked", "rescheduled") and document_state.get("documents"):
        appointment_id = appointment_state.get("appointment_id")
        for doc_result in document_state["documents"]:
            if doc_result.get("status") == "stored":
                document = db.get(PatientDocument, doc_result["document_id"])
                if document is not None and document.appointment_id is None:
                    document.appointment_id = appointment_id
        db.commit()

    # 7. Safety Agent (LLM) — nuance layer on what the pipeline is about to
    #    present back to the patient.
    aggregated_summary = (
        f"Routing result: {routing_state}\n"
        f"Appointment result: {appointment_state}\n"
        f"Document result: {document_state}"
    )
    safety_post_agent = build_safety_agent(db, workflow_run.id, SAFETY_VERDICT_POST)
    safety_post_turn = await _invoke_with_retry(
        invoker,
        safety_post_agent,
        initial_state={"safety_review_input": aggregated_summary},
        message=aggregated_summary,
    )
    verdict_post = safety_post_turn.state.get(SAFETY_VERDICT_POST, {"is_unsafe": False})
    update_workflow_state(
        db, workflow_run.id, current_step="safety_check_post", state_patch={"safety_verdict_post": verdict_post}
    )
    if verdict_post.get("is_unsafe"):
        update_workflow_state(
            db, workflow_run.id, status=WorkflowStatus.AWAITING_ESCALATION, current_step="safety_check_post"
        )
        return get_workflow_run(db, workflow_run.id)

    # 8. Follow-up (conditionally) — only meaningful once an appointment is real.
    followup_state: dict = {}
    if plan.get("needs_followup") and appointment_state.get("status") in ("booked", "rescheduled"):
        followup_agent = build_followup_agent(db, user, patient)
        followup_turn = await _invoke_with_retry(
            invoker, followup_agent, initial_state={"appointment_result": appointment_state}, message=request_text
        )
        followup_state = followup_turn.state.get(FOLLOWUP_RESULT, {})

    update_workflow_state(
        db,
        workflow_run.id,
        current_step="completed",
        status=WorkflowStatus.COMPLETED,
        state_patch={"followup_result": followup_state},
    )
    return get_workflow_run(db, workflow_run.id)


def _escalate_and_halt(
    db: Session,
    workflow_run_id: int,
    *,
    reason: EscalationReason,
    detail: str,
    current_step: str,
    extra_state: dict | None = None,
) -> None:
    escalation_result = raise_escalation(
        db, workflow_run_id=workflow_run_id, reason=reason, detail=detail, actor_role="system"
    )
    update_workflow_state(
        db,
        workflow_run_id,
        current_step=current_step,
        status=WorkflowStatus.AWAITING_ESCALATION,
        state_patch={"escalation": escalation_result, **(extra_state or {})},
    )


def _jsonable(value: dict) -> dict:
    return {k: (v.value if hasattr(v, "value") else v) for k, v in value.items()}
