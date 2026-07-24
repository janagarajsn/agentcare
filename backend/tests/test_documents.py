import io

from .conftest import auth_headers

PDF_BYTES = b"%PDF-1.4 fake ecg report content for testing\n"


def _upload(client, user, *, document_type="ecg", filename="ecg.pdf", content=PDF_BYTES, content_type="application/pdf", appointment_id=None):
    data = {"document_type": document_type}
    if appointment_id is not None:
        data["appointment_id"] = str(appointment_id)
    return client.post(
        "/documents/upload",
        data=data,
        files={"file": (filename, io.BytesIO(content), content_type)},
        headers=auth_headers(user),
    )


def test_upload_document_happy_path(client, patient_with_profile):
    user, _ = patient_with_profile
    response = _upload(client, user)
    assert response.status_code == 201
    body = response.json()
    assert body["document_type"] == "ecg"
    assert body["is_duplicate"] is False
    assert body["checksum"]


def test_upload_duplicate_document_flagged(client, patient_with_profile):
    user, _ = patient_with_profile
    first = _upload(client, user)
    assert first.status_code == 201

    second = _upload(client, user)
    assert second.status_code == 201
    assert second.json()["is_duplicate"] is True


def test_upload_unsupported_content_type_rejected(client, patient_with_profile):
    user, _ = patient_with_profile
    response = _upload(client, user, filename="malware.exe", content=b"MZ...", content_type="application/x-msdownload")
    assert response.status_code == 400


def test_upload_document_for_appointment_and_check_missing(
    client, patient_with_profile, open_slot
):
    user, _ = patient_with_profile
    booked = client.post("/appointments", json={"slot_id": open_slot.id}, headers=auth_headers(user)).json()

    missing_before = client.get(
        f"/documents/appointment/{booked['id']}/missing", headers=auth_headers(user)
    )
    assert missing_before.status_code == 200
    body_before = missing_before.json()
    assert body_before["department_name"] == "Cardiology"
    assert set(body_before["required"]) == {"ecg", "blood_report"}
    assert set(body_before["missing"]) == {"ecg", "blood_report"}

    upload_resp = _upload(client, user, appointment_id=booked["id"])
    assert upload_resp.status_code == 201

    missing_after = client.get(
        f"/documents/appointment/{booked['id']}/missing", headers=auth_headers(user)
    )
    body_after = missing_after.json()
    assert set(body_after["missing"]) == {"blood_report"}


def test_patient_cannot_view_another_patients_document(
    client, patient_with_profile, second_patient_with_profile
):
    user1, _ = patient_with_profile
    user2, _ = second_patient_with_profile

    uploaded = _upload(client, user1).json()

    response = client.get(f"/documents/{uploaded['id']}", headers=auth_headers(user2))
    assert response.status_code == 403


def test_upload_for_appointment_not_owned_rejected(
    client, patient_with_profile, second_patient_with_profile, open_slot
):
    user1, _ = patient_with_profile
    user2, _ = second_patient_with_profile
    booked = client.post("/appointments", json={"slot_id": open_slot.id}, headers=auth_headers(user1)).json()

    response = _upload(client, user2, appointment_id=booked["id"])
    assert response.status_code == 404


def test_patient_cannot_check_missing_documents_for_another_patients_appointment(
    client, patient_with_profile, second_patient_with_profile, open_slot
):
    user1, _ = patient_with_profile
    user2, _ = second_patient_with_profile
    booked = client.post("/appointments", json={"slot_id": open_slot.id}, headers=auth_headers(user1)).json()

    response = client.get(f"/documents/appointment/{booked['id']}/missing", headers=auth_headers(user2))
    assert response.status_code == 403


def test_list_my_documents(client, patient_with_profile):
    user, _ = patient_with_profile
    _upload(client, user, document_type="ecg")
    _upload(client, user, document_type="blood_report", content=b"different content entirely")

    response = client.get("/documents", headers=auth_headers(user))
    assert response.status_code == 200
    assert len(response.json()) == 2
