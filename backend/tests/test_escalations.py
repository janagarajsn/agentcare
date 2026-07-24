from app.db.models import EscalationReason, EscalationStatus, WorkflowStatus
from app.services.escalation_service import create_escalation
from app.services.workflow_service import create_workflow_run, get_workflow_run

from .conftest import auth_headers


def _make_escalation(db_session, patient_id, reason=EscalationReason.EMERGENCY_LANGUAGE):
    run = create_workflow_run(db_session, patient_id, "I have severe chest pain right now")
    escalation = create_escalation(
        db_session,
        workflow_run_id=run.id,
        reason=reason,
        detail="Patient message contains emergency language",
        actor_role="safety_agent",
    )
    return run, escalation


def test_create_escalation_marks_workflow_awaiting(db_session, patient_with_profile):
    _, profile = patient_with_profile
    run, escalation = _make_escalation(db_session, profile.id)

    assert escalation.status == EscalationStatus.OPEN
    db_session.refresh(run)
    assert run.status == WorkflowStatus.AWAITING_ESCALATION


def test_patient_cannot_list_escalations(client, patient_with_profile, db_session):
    user, profile = patient_with_profile
    _make_escalation(db_session, profile.id)

    response = client.get("/escalations", headers=auth_headers(user))
    assert response.status_code == 403


def test_staff_can_list_and_view_escalations(client, staff_user, patient_with_profile, db_session):
    _, profile = patient_with_profile
    _, escalation = _make_escalation(db_session, profile.id)

    listed = client.get("/escalations", headers=auth_headers(staff_user))
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    single = client.get(f"/escalations/{escalation.id}", headers=auth_headers(staff_user))
    assert single.status_code == 200
    assert single.json()["reason"] == "emergency_language"


def test_staff_can_approve_escalation_and_resume_workflow(client, staff_user, patient_with_profile, db_session):
    _, profile = patient_with_profile
    run, escalation = _make_escalation(db_session, profile.id)

    response = client.post(
        f"/escalations/{escalation.id}/resolve",
        json={"decision": "approved", "note": "Confirmed non-emergency, routing to cardiology"},
        headers=auth_headers(staff_user),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "approved"
    assert body["reviewed_by"] == staff_user.id

    refreshed = get_workflow_run(db_session, run.id)
    assert refreshed.status == WorkflowStatus.RUNNING


def test_staff_can_reject_escalation_and_fail_workflow(client, staff_user, patient_with_profile, db_session):
    _, profile = patient_with_profile
    run, escalation = _make_escalation(db_session, profile.id)

    response = client.post(
        f"/escalations/{escalation.id}/resolve",
        json={"decision": "rejected", "note": "Genuine emergency, directed patient to call emergency services"},
        headers=auth_headers(staff_user),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "rejected"

    refreshed = get_workflow_run(db_session, run.id)
    assert refreshed.status == WorkflowStatus.FAILED


def test_patient_cannot_resolve_escalation(client, patient_with_profile, db_session):
    user, profile = patient_with_profile
    _, escalation = _make_escalation(db_session, profile.id)

    response = client.post(
        f"/escalations/{escalation.id}/resolve",
        json={"decision": "approved", "note": "trying to self-approve"},
        headers=auth_headers(user),
    )
    assert response.status_code == 403


def test_cannot_resolve_already_resolved_escalation(client, staff_user, patient_with_profile, db_session):
    _, profile = patient_with_profile
    _, escalation = _make_escalation(db_session, profile.id)

    first = client.post(
        f"/escalations/{escalation.id}/resolve",
        json={"decision": "approved", "note": "first pass"},
        headers=auth_headers(staff_user),
    )
    assert first.status_code == 200

    second = client.post(
        f"/escalations/{escalation.id}/resolve",
        json={"decision": "rejected", "note": "trying again"},
        headers=auth_headers(staff_user),
    )
    assert second.status_code == 409
