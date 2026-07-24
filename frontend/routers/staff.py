from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from backend_client import BackendAPIError, BackendClient
from deps import require_staff
from templating import render

router = APIRouter(prefix="/staff")


def _client(user: dict) -> BackendClient:
    return BackendClient(user["_token"])


def _redirect(path: str, message: str, is_error: bool = False) -> RedirectResponse:
    msg_type = "error" if is_error else "success"
    return RedirectResponse(f"{path}?msg={quote(message)}&msg_type={msg_type}", status_code=303)


@router.get("/dashboard")
async def dashboard(request: Request, user: dict = Depends(require_staff)):
    client = _client(user)
    workflows = await client.get("/workflows")
    escalations = await client.get("/escalations")
    open_escalations = [e for e in escalations if e["status"] in ("open", "in_review")]

    status_counts: dict[str, int] = {}
    for w in workflows:
        status_counts[w["status"]] = status_counts.get(w["status"], 0) + 1

    return render(
        request,
        "staff/dashboard.html",
        {
            "active_nav": "dashboard",
            "total_workflows": len(workflows),
            "open_escalation_count": len(open_escalations),
            "status_counts": status_counts,
            "recent_workflows": sorted(workflows, key=lambda w: w["created_at"], reverse=True)[:8],
        },
    )


@router.get("/requests")
async def requests_page(request: Request, patient_id: str = "", user: dict = Depends(require_staff)):
    client = _client(user)
    params = None
    if patient_id.strip().isdigit():
        params = {"patient_id": int(patient_id)}
    workflows = await client.get("/workflows", params=params)
    return render(
        request,
        "staff/requests.html",
        {
            "active_nav": "requests",
            "workflows": sorted(workflows, key=lambda w: w["created_at"], reverse=True),
            "patient_id_filter": patient_id,
        },
    )


@router.get("/escalations")
async def escalations_page(request: Request, user: dict = Depends(require_staff)):
    client = _client(user)
    escalations = await client.get("/escalations")
    return render(
        request,
        "staff/escalations.html",
        {"active_nav": "escalations", "escalations": sorted(escalations, key=lambda e: e["created_at"], reverse=True)},
    )


@router.post("/escalations/{escalation_id}/resolve")
async def resolve_escalation(
    request: Request,
    escalation_id: int,
    decision: str = Form(...),
    note: str = Form(default=""),
    user: dict = Depends(require_staff),
):
    client = _client(user)
    try:
        await client.post(
            f"/escalations/{escalation_id}/resolve",
            json={"decision": decision, "note": note or None},
        )
    except BackendAPIError as exc:
        return _redirect("/staff/escalations", exc.detail, is_error=True)
    return _redirect("/staff/escalations", f"Escalation #{escalation_id} {decision}.")


@router.get("/admin")
async def admin_page(request: Request, user: dict = Depends(require_staff)):
    client = _client(user)
    departments = await client.get("/staff/departments")
    doctors = await client.get("/staff/doctors")
    slots = await client.get("/staff/slots")
    doctors_by_dept: dict[int, list] = {}
    for doc in doctors:
        doctors_by_dept.setdefault(doc["department_id"], []).append(doc)
    return render(
        request,
        "staff/admin.html",
        {
            "active_nav": "admin",
            "departments": departments,
            "doctors": doctors,
            "doctors_by_dept": doctors_by_dept,
            "slots": sorted(slots, key=lambda s: s["start_time"])[:50],
        },
    )


@router.post("/admin/departments")
async def create_department(
    request: Request, name: str = Form(...), description: str = Form(default=""), user: dict = Depends(require_staff)
):
    client = _client(user)
    try:
        await client.post("/staff/departments", json={"name": name, "description": description or None})
    except BackendAPIError as exc:
        return _redirect("/staff/admin", exc.detail, is_error=True)
    return _redirect("/staff/admin", f"Department '{name}' created.")


@router.post("/admin/doctors")
async def create_doctor(
    request: Request, department_id: int = Form(...), name: str = Form(...), user: dict = Depends(require_staff)
):
    client = _client(user)
    try:
        await client.post("/staff/doctors", json={"department_id": department_id, "name": name})
    except BackendAPIError as exc:
        return _redirect("/staff/admin", exc.detail, is_error=True)
    return _redirect("/staff/admin", f"Doctor '{name}' added.")


@router.post("/admin/slots")
async def create_slot(
    request: Request,
    doctor_id: int = Form(...),
    start_time: str = Form(...),
    end_time: str = Form(...),
    user: dict = Depends(require_staff),
):
    client = _client(user)
    try:
        await client.post(
            "/staff/slots", json={"doctor_id": doctor_id, "start_time": start_time, "end_time": end_time}
        )
    except BackendAPIError as exc:
        return _redirect("/staff/admin", exc.detail, is_error=True)
    return _redirect("/staff/admin", "Slot created.")


@router.get("/audit")
async def audit_page(request: Request, user: dict = Depends(require_staff)):
    client = _client(user)
    events = await client.get("/staff/audit-events")
    return render(request, "staff/audit.html", {"active_nav": "audit", "events": events})
