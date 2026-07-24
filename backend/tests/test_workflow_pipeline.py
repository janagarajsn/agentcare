import pytest

from app.agents.pipeline import run_agentic_workflow
from app.api.routes_workflows import get_agent_invoker
from app.db.models import (
    Appointment,
    AppointmentStatus,
    AuditEvent,
    Escalation,
    EscalationReason,
    PatientDocument,
    Reminder,
    WorkflowStatus,
)
from app.main import app

from .conftest import auth_headers
from .fake_agent_invoker import AlwaysFailingAgentInvoker, FakeAgentInvoker


def _safe_verdict_handler(state, message, call_tool):
    call_tool("record_safety_verdict", is_unsafe=False, category="none", reason="administrative request")


def _unsafe_verdict_handler(reason_text):
    def handler(state, message, call_tool):
        call_tool(
            "record_safety_verdict",
            is_unsafe=True,
            category="diagnosis_or_prescription_request",
            reason=reason_text,
        )

    return handler


def _coordinator_full_booking(state, message, call_tool):
    call_tool("resolve_patient")
    call_tool(
        "record_plan",
        needs_routing=True,
        needs_appointment=True,
        needs_document_check=bool(state.get("pending_filenames")),
        needs_followup=True,
        is_administrative_only=False,
    )


def _coordinator_reschedule_only(state, message, call_tool):
    # What a real coordinator sensibly decides for "reschedule my existing
    # appointment" — no NEW department needs resolving.
    call_tool("resolve_patient")
    call_tool(
        "record_plan",
        needs_routing=False,
        needs_appointment=True,
        needs_document_check=False,
        needs_followup=True,
        is_administrative_only=False,
    )


def _coordinator_document_only(state, message, call_tool):
    call_tool("resolve_patient")
    call_tool(
        "record_plan",
        needs_routing=False,
        needs_appointment=False,
        needs_document_check=True,
        needs_followup=False,
        is_administrative_only=False,
    )


def _routing_cardiology(state, message, call_tool):
    call_tool("resolve_department", department_query="Cardiology")


def _routing_nonexistent(state, message, call_tool):
    call_tool("resolve_department", department_query="Nonexistent Department XYZ")


def _appointment_book_first_slot(state, message, call_tool):
    routing_result = state.get("routing_result", {})
    department_id = routing_result.get("department_id")
    slots = call_tool("find_slots", department_id=department_id, start_after="", start_before="")
    if slots["count"] == 0:
        return
    first_slot_id = slots["slots"][0]["slot_id"]
    call_tool("book_slot", slot_id=first_slot_id, reason="Cardiology check-up")


def _appointment_reschedule_to(appointment_id, new_slot_id):
    def handler(state, message, call_tool):
        call_tool("reschedule_appointment", appointment_id=appointment_id, new_slot_id=new_slot_id)

    return handler


def _appointment_reschedule_via_lookup(new_slot_id):
    # Mirrors what a real Gemini agent must now do for "postpone my
    # appointment" — no explicit appointment_id in the message at all, so
    # it has to look its own way to the right one.
    def handler(state, message, call_tool):
        my_appointments = call_tool("list_my_active_appointments")
        if my_appointments["count"] != 1:
            return
        appointment_id = my_appointments["appointments"][0]["appointment_id"]
        call_tool("reschedule_appointment", appointment_id=appointment_id, new_slot_id=new_slot_id)

    return handler


def _appointment_reschedule_nonexistent(state, message, call_tool):
    # Simulates the agent finding no open slot at the requested time and
    # then (incorrectly) attempting to reschedule an appointment id that
    # doesn't exist for this patient — this must not crash the pipeline.
    call_tool("reschedule_appointment", appointment_id=999, new_slot_id=1)


def _document_store_pending(state, message, call_tool):
    for filename in state.get("pending_filenames", []):
        call_tool("store_pending_document", filename=filename)
    routing_result = state.get("routing_result", {})
    department_name = routing_result.get("department_name")
    if department_name:
        call_tool("check_missing_documents", department_name=department_name)


def _followup_schedule(state, message, call_tool):
    appointment_result = state.get("appointment_result", {})
    if appointment_result.get("status") in ("booked", "rescheduled"):
        call_tool("schedule_appointment_followups", appointment_id=appointment_result["appointment_id"])


@pytest.mark.asyncio
async def test_full_booking_workflow_happy_path(db_session, patient_with_profile, cardiology_department, cardiologist, open_slot):
    user, patient = patient_with_profile

    invoker = FakeAgentInvoker(
        {
            "safety_agent": _safe_verdict_handler,
            "coordinator_agent": _coordinator_full_booking,
            "routing_agent": _routing_cardiology,
            "appointment_agent": _appointment_book_first_slot,
            "followup_agent": _followup_schedule,
        }
    )

    workflow_run = await run_agentic_workflow(
        db_session,
        user,
        patient,
        "I need a cardiology appointment next week for a check-up.",
        agent_invoker=invoker,
    )

    assert workflow_run.status == WorkflowStatus.COMPLETED
    assert workflow_run.current_step == "completed"
    assert workflow_run.state["routing_result"]["status"] == "found"
    assert workflow_run.state["appointment_result"]["status"] == "booked"
    assert workflow_run.state["followup_result"]["status"] == "scheduled"

    appointment = db_session.get(Appointment, workflow_run.state["appointment_result"]["appointment_id"])
    assert appointment is not None
    assert appointment.status == AppointmentStatus.CONFIRMED
    assert appointment.patient_id == patient.id

    reminders = db_session.query(Reminder).filter_by(appointment_id=appointment.id).all()
    assert len(reminders) == 2

    assert "coordinator_agent" in invoker.invocations
    assert "routing_agent" in invoker.invocations
    assert "appointment_agent" in invoker.invocations
    assert "followup_agent" in invoker.invocations


@pytest.mark.asyncio
async def test_rescheduling_updates_reminders_instead_of_duplicating_them(
    db_session, patient_with_profile, cardiology_department, cardiologist, open_slot, another_open_slot
):
    """Regression test: previously, re-running the Follow-up Agent after a
    reschedule created a brand new pair of reminders without touching the
    ones from the original booking, leaving stale reminders pointing at a
    superseded appointment time. There must always be exactly one scheduled
    reminder per type per appointment, reflecting the CURRENT slot."""
    user, patient = patient_with_profile

    book_invoker = FakeAgentInvoker(
        {
            "safety_agent": _safe_verdict_handler,
            "coordinator_agent": _coordinator_full_booking,
            "routing_agent": _routing_cardiology,
            "appointment_agent": _appointment_book_first_slot,
            "followup_agent": _followup_schedule,
        }
    )
    booked_run = await run_agentic_workflow(
        db_session, user, patient, "I need a cardiology appointment.", agent_invoker=book_invoker
    )
    appointment_id = booked_run.state["appointment_result"]["appointment_id"]

    reminders_after_booking = db_session.query(Reminder).filter_by(appointment_id=appointment_id).all()
    assert len(reminders_after_booking) == 2
    original_times = {r.reminder_type: r.scheduled_at for r in reminders_after_booking}

    reschedule_invoker = FakeAgentInvoker(
        {
            "safety_agent": _safe_verdict_handler,
            "coordinator_agent": _coordinator_full_booking,
            "routing_agent": _routing_cardiology,
            "appointment_agent": _appointment_reschedule_to(appointment_id, another_open_slot.id),
            "followup_agent": _followup_schedule,
        }
    )
    rescheduled_run = await run_agentic_workflow(
        db_session, user, patient, "Please move my appointment to the later slot.", agent_invoker=reschedule_invoker
    )
    assert rescheduled_run.state["appointment_result"]["status"] == "rescheduled"

    reminders_after_reschedule = db_session.query(Reminder).filter_by(appointment_id=appointment_id).all()
    assert len(reminders_after_reschedule) == 2  # still 2, not 4

    new_times = {r.reminder_type: r.scheduled_at for r in reminders_after_reschedule}
    assert new_times != original_times
    for reminder_type, scheduled_at in new_times.items():
        assert scheduled_at != original_times[reminder_type]


@pytest.mark.asyncio
async def test_reschedule_only_request_still_reschedules_when_routing_not_needed(
    db_session, patient_with_profile, cardiology_department, cardiologist, open_slot, another_open_slot
):
    """Regression test: a real coordinator sensibly sets needs_routing=False
    for 'reschedule my existing appointment' (no NEW department to resolve).
    Previously the pipeline required routing_result.status == 'found' for
    the Appointment Agent to run AT ALL, so needs_routing=False silently
    skipped the Appointment Agent entirely — the workflow completed having
    done nothing, and no reschedule was ever recorded."""
    user, patient = patient_with_profile

    book_invoker = FakeAgentInvoker(
        {
            "safety_agent": _safe_verdict_handler,
            "coordinator_agent": _coordinator_full_booking,
            "routing_agent": _routing_cardiology,
            "appointment_agent": _appointment_book_first_slot,
            "followup_agent": _followup_schedule,
        }
    )
    booked_run = await run_agentic_workflow(
        db_session, user, patient, "I need a cardiology appointment.", agent_invoker=book_invoker
    )
    appointment_id = booked_run.state["appointment_result"]["appointment_id"]

    reschedule_invoker = FakeAgentInvoker(
        {
            "safety_agent": _safe_verdict_handler,
            "coordinator_agent": _coordinator_reschedule_only,
            "appointment_agent": _appointment_reschedule_to(appointment_id, another_open_slot.id),
            "followup_agent": _followup_schedule,
        }
    )
    rescheduled_run = await run_agentic_workflow(
        db_session, user, patient, "Please postpone my appointment to a later date.", agent_invoker=reschedule_invoker
    )

    assert "routing_agent" not in reschedule_invoker.invocations
    assert "appointment_agent" in reschedule_invoker.invocations
    assert rescheduled_run.status == WorkflowStatus.COMPLETED
    assert rescheduled_run.state["appointment_result"]["status"] == "rescheduled"
    assert rescheduled_run.state["appointment_result"]["slot_id"] == another_open_slot.id

    appointment = db_session.get(Appointment, appointment_id)
    assert appointment.slot_id == another_open_slot.id

    audit_reasons = [
        e.action
        for e in db_session.query(AuditEvent).filter_by(entity_type="Appointment", entity_id=appointment_id).all()
    ]
    assert "appointment_rescheduled" in audit_reasons


@pytest.mark.asyncio
async def test_appointment_agent_resolves_my_appointment_via_lookup_when_no_id_given(
    db_session, patient_with_profile, cardiology_department, cardiologist, open_slot, another_open_slot
):
    """Regression test: real natural-language requests like 'postpone my
    appointment' never state a raw numeric appointment_id. Previously the
    Appointment Agent had no tool to look up the patient's own appointments,
    so it silently called nothing and the workflow completed having done
    nothing. It must be able to resolve this via list_my_active_appointments."""
    user, patient = patient_with_profile

    book_invoker = FakeAgentInvoker(
        {
            "safety_agent": _safe_verdict_handler,
            "coordinator_agent": _coordinator_full_booking,
            "routing_agent": _routing_cardiology,
            "appointment_agent": _appointment_book_first_slot,
            "followup_agent": _followup_schedule,
        }
    )
    booked_run = await run_agentic_workflow(
        db_session, user, patient, "I need a cardiology appointment.", agent_invoker=book_invoker
    )
    appointment_id = booked_run.state["appointment_result"]["appointment_id"]

    reschedule_invoker = FakeAgentInvoker(
        {
            "safety_agent": _safe_verdict_handler,
            "coordinator_agent": _coordinator_reschedule_only,
            "appointment_agent": _appointment_reschedule_via_lookup(another_open_slot.id),
            "followup_agent": _followup_schedule,
        }
    )
    rescheduled_run = await run_agentic_workflow(
        db_session, user, patient, "Can you postpone my appointment to a later date please?",
        agent_invoker=reschedule_invoker,
    )

    assert rescheduled_run.state["appointment_result"]["status"] == "rescheduled"
    assert rescheduled_run.state["appointment_result"]["appointment_id"] == appointment_id
    assert rescheduled_run.state["appointment_result"]["slot_id"] == another_open_slot.id

    appointment = db_session.get(Appointment, appointment_id)
    assert appointment.slot_id == another_open_slot.id


@pytest.mark.asyncio
async def test_appointment_agent_acting_on_nonexistent_appointment_does_not_crash(
    db_session, patient_with_profile, cardiology_department, cardiologist, open_slot
):
    """Regression test: if the agent finds no matching slot and then tries
    to reschedule/cancel an appointment id that doesn't exist for this
    patient, the pipeline must complete gracefully (structured 'not_found'
    result) instead of an uncaught AppointmentNotFoundError crashing the
    whole request."""
    user, patient = patient_with_profile

    invoker = FakeAgentInvoker(
        {
            "safety_agent": _safe_verdict_handler,
            "coordinator_agent": _coordinator_full_booking,
            "routing_agent": _routing_cardiology,
            "appointment_agent": _appointment_reschedule_nonexistent,
            "followup_agent": _followup_schedule,
        }
    )

    workflow_run = await run_agentic_workflow(
        db_session,
        user,
        patient,
        "Please move my appointment to a different time, I don't remember the id.",
        agent_invoker=invoker,
    )

    assert workflow_run.status == WorkflowStatus.COMPLETED
    assert workflow_run.state["appointment_result"]["status"] == "not_found"


@pytest.mark.asyncio
async def test_deterministic_emergency_escalates_and_halts(db_session, patient_with_profile):
    user, patient = patient_with_profile
    invoker = FakeAgentInvoker({})

    workflow_run = await run_agentic_workflow(
        db_session,
        user,
        patient,
        "I'm having severe chest pain right now, please help",
        agent_invoker=invoker,
    )

    assert workflow_run.status == WorkflowStatus.AWAITING_ESCALATION
    assert workflow_run.current_step == "safety_pre_check_deterministic"
    assert invoker.invocations == []  # halted before any LLM call

    escalation = db_session.query(Escalation).filter_by(workflow_run_id=workflow_run.id).first()
    assert escalation is not None
    assert escalation.reason == EscalationReason.EMERGENCY_LANGUAGE


@pytest.mark.asyncio
async def test_llm_safety_agent_catches_what_keywords_miss(db_session, patient_with_profile):
    user, patient = patient_with_profile
    invoker = FakeAgentInvoker(
        {
            "safety_agent": _unsafe_verdict_handler("Request implies a clinical judgment the system must not make"),
        }
    )

    workflow_run = await run_agentic_workflow(
        db_session,
        user,
        patient,
        "Based on my symptoms, which of these two conditions do you think it is?",
        agent_invoker=invoker,
    )

    assert workflow_run.status == WorkflowStatus.AWAITING_ESCALATION
    assert workflow_run.current_step == "safety_check_pre"

    escalation = db_session.query(Escalation).filter_by(workflow_run_id=workflow_run.id).first()
    assert escalation is not None
    assert escalation.reason == EscalationReason.DIAGNOSIS_OR_PRESCRIPTION_REQUEST

    # Coordinator/routing/appointment never ran — the pipeline halted first.
    assert "coordinator_agent" not in invoker.invocations


@pytest.mark.asyncio
async def test_unresolvable_department_escalates(db_session, patient_with_profile):
    user, patient = patient_with_profile
    invoker = FakeAgentInvoker(
        {
            "safety_agent": _safe_verdict_handler,
            "coordinator_agent": _coordinator_full_booking,
            "routing_agent": _routing_nonexistent,
        }
    )

    workflow_run = await run_agentic_workflow(
        db_session,
        user,
        patient,
        "I need to see someone about a department that doesn't exist here.",
        agent_invoker=invoker,
    )

    assert workflow_run.status == WorkflowStatus.AWAITING_ESCALATION
    assert workflow_run.current_step == "routing"

    escalation = db_session.query(Escalation).filter_by(workflow_run_id=workflow_run.id).first()
    assert escalation is not None
    assert escalation.reason == EscalationReason.UNSUPPORTED_DEPARTMENT

    # Appointment/followup never ran since routing failed to resolve.
    assert "appointment_agent" not in invoker.invocations
    assert "followup_agent" not in invoker.invocations


@pytest.mark.asyncio
async def test_document_only_request_does_not_touch_appointments(db_session, patient_with_profile):
    user, patient = patient_with_profile
    invoker = FakeAgentInvoker(
        {
            "safety_agent": _safe_verdict_handler,
            "coordinator_agent": _coordinator_document_only,
            "document_agent": _document_store_pending,
        }
    )

    pending_documents = {"ecg_march.pdf": (b"%PDF-1.4 fake ecg content", "application/pdf")}

    workflow_run = await run_agentic_workflow(
        db_session,
        user,
        patient,
        "Please attach my new ECG to my file.",
        pending_documents=pending_documents,
        agent_invoker=invoker,
    )

    assert workflow_run.status == WorkflowStatus.COMPLETED
    assert workflow_run.state["appointment_result"] == {}

    document_result = workflow_run.state["document_result"]
    assert len(document_result["documents"]) == 1
    assert document_result["documents"][0]["status"] == "stored"

    stored_doc = db_session.query(PatientDocument).filter_by(patient_id=patient.id).first()
    assert stored_doc is not None
    assert stored_doc.document_type.value == "ecg"
    assert stored_doc.appointment_id is None

    assert "routing_agent" not in invoker.invocations
    assert "appointment_agent" not in invoker.invocations


@pytest.mark.asyncio
async def test_workflow_state_persists_across_a_fresh_db_read(db_session, patient_with_profile, cardiology_department, cardiologist, open_slot):
    user, patient = patient_with_profile
    invoker = FakeAgentInvoker(
        {
            "safety_agent": _safe_verdict_handler,
            "coordinator_agent": _coordinator_full_booking,
            "routing_agent": _routing_cardiology,
            "appointment_agent": _appointment_book_first_slot,
            "followup_agent": _followup_schedule,
        }
    )

    workflow_run = await run_agentic_workflow(
        db_session, user, patient, "Book me a cardiology appointment.", agent_invoker=invoker
    )
    workflow_run_id = workflow_run.id

    # Simulate a process restart: read the same row back from a clean query.
    from app.db.models import WorkflowRun

    reloaded = db_session.query(WorkflowRun).filter_by(id=workflow_run_id).first()
    assert reloaded.status == WorkflowStatus.COMPLETED
    assert reloaded.state["appointment_result"]["status"] == "booked"
    assert reloaded.state["plan"]["needs_appointment"] is True


@pytest.mark.asyncio
async def test_persistent_model_failure_retries_then_marks_workflow_failed(db_session, patient_with_profile):
    user, patient = patient_with_profile
    invoker = AlwaysFailingAgentInvoker()

    workflow_run = await run_agentic_workflow(
        db_session, user, patient, "I need a general medicine appointment.", agent_invoker=invoker
    )

    assert invoker.attempts == 2  # one retry after the first failure
    assert workflow_run.status == WorkflowStatus.FAILED
    assert workflow_run.current_step == "agent_invocation_failed"
    assert "error" in workflow_run.state


def _override_invoker(invoker):
    app.dependency_overrides[get_agent_invoker] = lambda: invoker


def _clear_invoker_override():
    app.dependency_overrides.pop(get_agent_invoker, None)


def test_submit_request_endpoint_happy_path_returns_persisted_results(
    client, patient_with_profile, cardiology_department, cardiologist, open_slot
):
    user, patient = patient_with_profile
    invoker = FakeAgentInvoker(
        {
            "safety_agent": _safe_verdict_handler,
            "coordinator_agent": _coordinator_full_booking,
            "routing_agent": _routing_cardiology,
            "appointment_agent": _appointment_book_first_slot,
            "followup_agent": _followup_schedule,
        }
    )
    _override_invoker(invoker)
    try:
        response = client.post(
            "/workflows/submit",
            data={"request_text": "I need a cardiology appointment next week for a check-up."},
            headers=auth_headers(user),
        )
    finally:
        _clear_invoker_override()

    assert response.status_code == 201
    body = response.json()
    assert body["workflow_run"]["status"] == "completed"
    assert body["appointment"] is not None
    assert body["appointment"]["status"] == "confirmed"
    assert body["appointment"]["patient_id"] == patient.id
    assert len(body["reminders"]) == 2
    assert body["escalation"] is None


def test_submit_request_endpoint_with_attached_file(client, patient_with_profile):
    user, patient = patient_with_profile
    invoker = FakeAgentInvoker(
        {
            "safety_agent": _safe_verdict_handler,
            "coordinator_agent": _coordinator_document_only,
            "document_agent": _document_store_pending,
        }
    )
    _override_invoker(invoker)
    try:
        response = client.post(
            "/workflows/submit",
            data={"request_text": "Please attach my new ECG."},
            files={"files": ("ecg_report.pdf", b"%PDF-1.4 fake ecg content", "application/pdf")},
            headers=auth_headers(user),
        )
    finally:
        _clear_invoker_override()

    assert response.status_code == 201
    body = response.json()
    assert body["workflow_run"]["status"] == "completed"
    assert body["appointment"] is None
    assert len(body["documents"]) == 1
    assert body["documents"][0]["document_type"] == "ecg"


def test_submit_request_endpoint_emergency_returns_escalation(client, patient_with_profile):
    user, patient = patient_with_profile
    # Defensive: the deterministic screen should halt before any agent call,
    # but override with an always-failing fake anyway so this test can never
    # accidentally reach a real model.
    _override_invoker(AlwaysFailingAgentInvoker())
    try:
        response = client.post(
            "/workflows/submit",
            data={"request_text": "I'm having severe chest pain right now, please help"},
            headers=auth_headers(user),
        )
    finally:
        _clear_invoker_override()

    assert response.status_code == 201
    body = response.json()
    assert body["workflow_run"]["status"] == "awaiting_escalation"
    assert body["escalation"] is not None
    assert body["escalation"]["reason"] == "emergency_language"


def test_submit_request_endpoint_requires_patient_role(client, staff_user):
    response = client.post(
        "/workflows/submit",
        data={"request_text": "Book me an appointment."},
        headers=auth_headers(staff_user),
    )
    assert response.status_code == 403
