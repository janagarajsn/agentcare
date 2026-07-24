from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse

from backend_client import BackendAPIError, BackendClient
from deps import require_patient
from templating import render

router = APIRouter(prefix="/patient")


def _client(user: dict) -> BackendClient:
    return BackendClient(user["_token"])


def _redirect(path: str, message: str, is_error: bool = False) -> RedirectResponse:
    msg_type = "error" if is_error else "success"
    return RedirectResponse(f"{path}?msg={quote(message)}&msg_type={msg_type}", status_code=303)


@router.get("/dashboard")
async def dashboard(request: Request, user: dict = Depends(require_patient)):
    client = _client(user)
    appointments = await client.get("/appointments")
    reminders = await client.get("/patients/me/reminders")
    workflows = await client.get("/workflows")
    documents = await client.get("/documents")

    upcoming = sorted(
        (a for a in appointments if a["status"] in ("confirmed", "pending", "rescheduled")),
        key=lambda a: a["slot_start_time"],
    )

    return render(
        request,
        "patient/dashboard.html",
        {
            "active_nav": "dashboard",
            "appointment_count": len(upcoming),
            "next_appointment": upcoming[0] if upcoming else None,
            "document_count": len(documents),
            "reminder_count": len(reminders),
            "recent_workflows": sorted(workflows, key=lambda w: w["created_at"], reverse=True)[:5],
        },
    )


@router.get("/submit")
async def submit_form(request: Request, user: dict = Depends(require_patient)):
    return render(request, "patient/submit.html", {"active_nav": "submit", "result": None})


@router.post("/submit")
async def submit_action(
    request: Request,
    request_text: str = Form(...),
    files: list[UploadFile] = File(default=[]),
    user: dict = Depends(require_patient),
):
    client = _client(user)

    upload_files = []
    for upload in files:
        if upload.filename:
            content = await upload.read()
            upload_files.append(("files", (upload.filename, content, upload.content_type or "application/octet-stream")))

    try:
        # The agent pipeline can make several sequential/parallel real LLM
        # calls (with retries) before responding — give it much longer than
        # the default timeout so a slow-but-succeeding run doesn't get cut
        # off client-side.
        result = await client.post(
            "/workflows/submit",
            data={"request_text": request_text},
            files=upload_files or None,
            timeout=180,
        )
    except BackendAPIError as exc:
        return render(
            request,
            "patient/submit.html",
            {"active_nav": "submit", "result": None, "error": exc.detail},
        )

    return render(request, "patient/submit.html", {"active_nav": "submit", "result": result, "error": None})


@router.get("/appointments")
async def appointments_page(request: Request, user: dict = Depends(require_patient)):
    client = _client(user)
    appointments = await client.get("/appointments")
    departments = await client.get("/appointments/departments")
    return render(
        request,
        "patient/appointments.html",
        {
            "active_nav": "appointments",
            "appointments": sorted(appointments, key=lambda a: a["slot_start_time"]),
            "departments": departments,
        },
    )


@router.get("/appointments/slots")
async def browse_slots(request: Request, department_id: int, user: dict = Depends(require_patient)):
    client = _client(user)
    slots = await client.get("/appointments/slots", params={"department_id": department_id})
    return render(
        request,
        "patient/_slot_options.html",
        {"slots": slots["slots"]},
    )


@router.post("/appointments/book")
async def book_appointment(
    request: Request,
    slot_id: int = Form(...),
    reason: str = Form(default=""),
    user: dict = Depends(require_patient),
):
    client = _client(user)
    try:
        await client.post("/appointments", json={"slot_id": slot_id, "reason": reason or None})
    except BackendAPIError as exc:
        return _redirect("/patient/appointments", exc.detail, is_error=True)
    return _redirect("/patient/appointments", "Appointment booked.")


@router.post("/appointments/{appointment_id}/reschedule")
async def reschedule_appointment(
    request: Request,
    appointment_id: int,
    new_slot_id: int = Form(...),
    user: dict = Depends(require_patient),
):
    client = _client(user)
    try:
        await client.post(f"/appointments/{appointment_id}/reschedule", json={"new_slot_id": new_slot_id})
    except BackendAPIError as exc:
        return _redirect("/patient/appointments", exc.detail, is_error=True)
    return _redirect("/patient/appointments", "Appointment rescheduled.")


@router.post("/appointments/{appointment_id}/cancel")
async def cancel_appointment(request: Request, appointment_id: int, user: dict = Depends(require_patient)):
    client = _client(user)
    try:
        await client.post(f"/appointments/{appointment_id}/cancel")
    except BackendAPIError as exc:
        return _redirect("/patient/appointments", exc.detail, is_error=True)
    return _redirect("/patient/appointments", "Appointment cancelled.")


@router.get("/documents")
async def documents_page(request: Request, user: dict = Depends(require_patient)):
    client = _client(user)
    documents = await client.get("/documents")
    appointments = await client.get("/appointments")
    return render(
        request,
        "patient/documents.html",
        {
            "active_nav": "documents",
            "documents": sorted(documents, key=lambda d: d["created_at"], reverse=True),
            "appointments": appointments,
        },
    )


@router.post("/documents/upload")
async def upload_document(
    request: Request,
    document_type: str = Form(...),
    appointment_id: str = Form(default=""),
    file: UploadFile = File(...),
    user: dict = Depends(require_patient),
):
    client = _client(user)
    content = await file.read()
    data = {"document_type": document_type}
    if appointment_id:
        data["appointment_id"] = appointment_id

    try:
        await client.post(
            "/documents/upload",
            data=data,
            files={"file": (file.filename, content, file.content_type or "application/octet-stream")},
        )
    except BackendAPIError as exc:
        return _redirect("/patient/documents", exc.detail, is_error=True)
    return _redirect("/patient/documents", "Document uploaded.")


@router.get("/reminders")
async def reminders_page(request: Request, user: dict = Depends(require_patient)):
    client = _client(user)
    reminders = await client.get("/patients/me/reminders")
    return render(
        request,
        "patient/reminders.html",
        {"active_nav": "reminders", "reminders": sorted(reminders, key=lambda r: r["scheduled_at"])},
    )
