from app.db.models import User, UserRole

from .conftest import auth_headers

PATIENT_PAYLOAD = {
    "name": "Test Patient",
    "email": "patient.tester@agentcare.example",
    "password": "PatientPass123!",
    "date_of_birth": "1992-06-15",
    "phone": "+1-555-9999",
    "preferred_language": "en",
    "emergency_contact": "Someone Else, +1-555-8888",
}


def test_register_patient_creates_user_and_profile(client, db_session):
    response = client.post("/auth/register", json=PATIENT_PAYLOAD)
    assert response.status_code == 201

    body = response.json()
    assert body["email"] == PATIENT_PAYLOAD["email"]
    assert body["role"] == "patient"
    assert "password" not in body
    assert "password_hash" not in body

    user = db_session.query(User).filter_by(email=PATIENT_PAYLOAD["email"]).first()
    assert user is not None
    assert user.patient_profile is not None
    assert user.patient_profile.phone == PATIENT_PAYLOAD["phone"]


def test_register_duplicate_email_rejected(client):
    first = client.post("/auth/register", json=PATIENT_PAYLOAD)
    assert first.status_code == 201

    second = client.post("/auth/register", json=PATIENT_PAYLOAD)
    assert second.status_code == 409


def test_login_returns_valid_jwt_and_updates_last_login(client, db_session):
    client.post("/auth/register", json=PATIENT_PAYLOAD)

    response = client.post(
        "/auth/login",
        data={"username": PATIENT_PAYLOAD["email"], "password": PATIENT_PAYLOAD["password"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["refresh_token"]

    me = client.get("/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200
    assert me.json()["email"] == PATIENT_PAYLOAD["email"]

    user = db_session.query(User).filter_by(email=PATIENT_PAYLOAD["email"]).first()
    assert user.last_login_at is not None


def test_login_wrong_password_rejected(client):
    client.post("/auth/register", json=PATIENT_PAYLOAD)

    response = client.post(
        "/auth/login",
        data={"username": PATIENT_PAYLOAD["email"], "password": "WrongPassword!"},
    )
    assert response.status_code == 401


def test_login_unknown_email_rejected(client):
    response = client.post(
        "/auth/login",
        data={"username": "nobody@agentcare.example", "password": "whatever123"},
    )
    assert response.status_code == 401


def test_refresh_token_issues_new_access_token(client):
    client.post("/auth/register", json=PATIENT_PAYLOAD)
    login = client.post(
        "/auth/login",
        data={"username": PATIENT_PAYLOAD["email"], "password": PATIENT_PAYLOAD["password"]},
    ).json()

    refreshed = client.post("/auth/refresh", json={"refresh_token": login["refresh_token"]})
    assert refreshed.status_code == 200
    assert refreshed.json()["access_token"]


def test_access_token_rejected_at_refresh_endpoint(client):
    client.post("/auth/register", json=PATIENT_PAYLOAD)
    login = client.post(
        "/auth/login",
        data={"username": PATIENT_PAYLOAD["email"], "password": PATIENT_PAYLOAD["password"]},
    ).json()

    response = client.post("/auth/refresh", json={"refresh_token": login["access_token"]})
    assert response.status_code == 401


def test_protected_endpoint_requires_token(client):
    response = client.get("/auth/me")
    assert response.status_code == 401


def test_staff_only_endpoint_returns_403_for_patient(client):
    client.post("/auth/register", json=PATIENT_PAYLOAD)
    login = client.post(
        "/auth/login",
        data={"username": PATIENT_PAYLOAD["email"], "password": PATIENT_PAYLOAD["password"]},
    ).json()

    response = client.post(
        "/staff/users",
        json={"name": "New Staff", "email": "new.staff@agentcare.example", "password": "NewStaff123!", "role": "staff"},
        headers={"Authorization": f"Bearer {login['access_token']}"},
    )
    assert response.status_code == 403


def test_admin_only_endpoint_returns_403_for_staff(client, staff_user):
    response = client.post(
        "/staff/users",
        json={"name": "New Staff", "email": "new.staff2@agentcare.example", "password": "NewStaff123!", "role": "staff"},
        headers=auth_headers(staff_user),
    )
    assert response.status_code == 403


def test_admin_can_create_staff_account(client, admin_user, db_session):
    response = client.post(
        "/staff/users",
        json={"name": "New Staff", "email": "new.staff3@agentcare.example", "password": "NewStaff123!", "role": "staff"},
        headers=auth_headers(admin_user),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["role"] == "staff"

    created = db_session.query(User).filter_by(email="new.staff3@agentcare.example").first()
    assert created is not None
    assert created.role == UserRole.STAFF


def test_admin_cannot_create_patient_via_staff_endpoint(client, admin_user):
    response = client.post(
        "/staff/users",
        json={"name": "Sneaky", "email": "sneaky@agentcare.example", "password": "Sneaky123!", "role": "patient"},
        headers=auth_headers(admin_user),
    )
    assert response.status_code == 409


def test_inactive_user_cannot_login(client, db_session):
    client.post("/auth/register", json=PATIENT_PAYLOAD)
    user = db_session.query(User).filter_by(email=PATIENT_PAYLOAD["email"]).first()
    user.is_active = False
    db_session.commit()

    response = client.post(
        "/auth/login",
        data={"username": PATIENT_PAYLOAD["email"], "password": PATIENT_PAYLOAD["password"]},
    )
    assert response.status_code == 401
