from app.db.models import AppointmentStatus, Reminder, ReminderStatus, SlotStatus

from .conftest import auth_headers


def test_patient_can_list_active_departments(client, patient_with_profile, cardiology_department):
    user, _ = patient_with_profile
    response = client.get("/appointments/departments", headers=auth_headers(user))
    assert response.status_code == 200
    names = [d["name"] for d in response.json()]
    assert "Cardiology" in names


def test_book_appointment_happy_path(client, patient_with_profile, open_slot, db_session):
    user, profile = patient_with_profile

    response = client.post(
        "/appointments",
        json={"slot_id": open_slot.id, "reason": "Cardiology follow-up"},
        headers=auth_headers(user),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "confirmed"
    assert body["slot_id"] == open_slot.id
    # The API must expose the real scheduled visit time and a real doctor
    # name/department — not just raw ids the frontend would have no way to
    # turn into "when is my appointment" and "who is it with".
    assert body["doctor_name"] == "Dr. Fixture Cardio"
    assert body["department_name"] == "Cardiology"
    assert body["slot_start_time"] == open_slot.start_time.isoformat()
    assert body["slot_end_time"] == open_slot.end_time.isoformat()

    db_session.refresh(open_slot)
    assert open_slot.status == SlotStatus.BOOKED


def test_book_appointment_slot_already_booked_conflict(client, patient_with_profile, second_patient_with_profile, open_slot):
    user1, _ = patient_with_profile
    user2, _ = second_patient_with_profile

    first = client.post("/appointments", json={"slot_id": open_slot.id}, headers=auth_headers(user1))
    assert first.status_code == 201

    second = client.post("/appointments", json={"slot_id": open_slot.id}, headers=auth_headers(user2))
    assert second.status_code == 409


def test_book_appointment_patient_double_booking_conflict(
    client, patient_with_profile, open_slot, overlapping_slot
):
    user, _ = patient_with_profile

    first = client.post("/appointments", json={"slot_id": open_slot.id}, headers=auth_headers(user))
    assert first.status_code == 201

    second = client.post("/appointments", json={"slot_id": overlapping_slot.id}, headers=auth_headers(user))
    assert second.status_code == 409


def test_reschedule_appointment_happy_path(client, patient_with_profile, open_slot, another_open_slot, db_session):
    user, _ = patient_with_profile
    booked = client.post("/appointments", json={"slot_id": open_slot.id}, headers=auth_headers(user)).json()

    response = client.post(
        f"/appointments/{booked['id']}/reschedule",
        json={"new_slot_id": another_open_slot.id},
        headers=auth_headers(user),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["slot_id"] == another_open_slot.id
    assert body["status"] == "rescheduled"

    db_session.refresh(open_slot)
    db_session.refresh(another_open_slot)
    assert open_slot.status == SlotStatus.OPEN
    assert another_open_slot.status == SlotStatus.BOOKED


def test_reschedule_to_unavailable_slot_conflict(
    client, patient_with_profile, second_patient_with_profile, open_slot, another_open_slot
):
    user1, _ = patient_with_profile
    user2, _ = second_patient_with_profile

    booked = client.post("/appointments", json={"slot_id": open_slot.id}, headers=auth_headers(user1)).json()
    client.post("/appointments", json={"slot_id": another_open_slot.id}, headers=auth_headers(user2))

    response = client.post(
        f"/appointments/{booked['id']}/reschedule",
        json={"new_slot_id": another_open_slot.id},
        headers=auth_headers(user1),
    )
    assert response.status_code == 409


def test_cancel_appointment_happy_path(client, patient_with_profile, open_slot, db_session):
    user, _ = patient_with_profile
    booked = client.post("/appointments", json={"slot_id": open_slot.id}, headers=auth_headers(user)).json()

    response = client.post(f"/appointments/{booked['id']}/cancel", headers=auth_headers(user))
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"

    db_session.refresh(open_slot)
    assert open_slot.status == SlotStatus.OPEN


def test_cancel_appointment_also_cancels_its_scheduled_reminders(client, patient_with_profile, open_slot, db_session):
    user, _ = patient_with_profile
    booked = client.post("/appointments", json={"slot_id": open_slot.id}, headers=auth_headers(user)).json()

    reminder = client.post(
        f"/appointments/{booked['id']}/reminders",
        json={"reminder_type": "appointment_reminder", "scheduled_at": "2030-01-06T09:00:00"},
        headers=auth_headers(user),
    ).json()
    assert reminder["status"] == "scheduled"

    response = client.post(f"/appointments/{booked['id']}/cancel", headers=auth_headers(user))
    assert response.status_code == 200

    reminder_row = db_session.get(Reminder, reminder["id"])
    db_session.refresh(reminder_row)
    assert reminder_row.status == ReminderStatus.CANCELLED


def test_cancel_already_cancelled_appointment_rejected(client, patient_with_profile, open_slot):
    user, _ = patient_with_profile
    booked = client.post("/appointments", json={"slot_id": open_slot.id}, headers=auth_headers(user)).json()
    client.post(f"/appointments/{booked['id']}/cancel", headers=auth_headers(user))

    response = client.post(f"/appointments/{booked['id']}/cancel", headers=auth_headers(user))
    assert response.status_code == 409


def test_patient_cannot_view_another_patients_appointment(
    client, patient_with_profile, second_patient_with_profile, open_slot
):
    user1, _ = patient_with_profile
    user2, _ = second_patient_with_profile
    booked = client.post("/appointments", json={"slot_id": open_slot.id}, headers=auth_headers(user1)).json()

    response = client.get(f"/appointments/{booked['id']}", headers=auth_headers(user2))
    assert response.status_code == 403


def test_staff_can_list_all_appointments(client, patient_with_profile, open_slot, staff_user):
    user, _ = patient_with_profile
    client.post("/appointments", json={"slot_id": open_slot.id}, headers=auth_headers(user))

    response = client.get("/appointments", headers=auth_headers(staff_user))
    assert response.status_code == 200
    assert len(response.json()) == 1


def test_browse_available_slots_filters_by_department(client, patient_with_profile, open_slot, cardiology_department):
    user, _ = patient_with_profile
    response = client.get(
        f"/appointments/slots?department_id={cardiology_department.id}", headers=auth_headers(user)
    )
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["slots"][0]["slot_id"] == open_slot.id
