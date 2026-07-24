from urllib.parse import quote

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from backend_client import BackendAPIError, BackendClient
from config import get_settings
from deps import dashboard_path
from templating import render

router = APIRouter()

_ERROR_MESSAGES = {
    "session_expired": "Your session expired — please log in again.",
    "patient_only": "That page is only available to patients.",
    "staff_only": "That page is only available to hospital staff.",
}


@router.get("/login")
async def login_form(request: Request):
    # Always show the form — even with a valid session cookie present — so
    # there's always a way back to it (e.g. to log in as a different user)
    # without having to find the logout link first. Only "/" auto-redirects
    # based on session state.
    error_code = request.query_params.get("error")
    error = _ERROR_MESSAGES.get(error_code) if error_code else None
    return render(request, "login.html", {"error": error})


@router.post("/login")
async def login_submit(request: Request, email: str = Form(...), password: str = Form(...)):
    client = BackendClient()
    try:
        tokens = await client.post("/auth/login", data={"username": email, "password": password})
    except BackendAPIError as exc:
        return render(request, "login.html", {"error": exc.detail})

    me = await BackendClient(tokens["access_token"]).get("/auth/me")
    destination = dashboard_path(me)

    settings = get_settings()
    response = RedirectResponse(destination, status_code=303)
    response.set_cookie(
        "access_token", tokens["access_token"], httponly=True, samesite="lax", secure=settings.cookie_secure
    )
    response.set_cookie(
        "refresh_token", tokens["refresh_token"], httponly=True, samesite="lax", secure=settings.cookie_secure
    )
    return response


@router.get("/register")
async def register_form(request: Request):
    return render(request, "register.html", {"error": None})


@router.post("/register")
async def register_submit(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    phone: str = Form(default=""),
    date_of_birth: str = Form(default=""),
    emergency_contact: str = Form(default=""),
):
    payload = {
        "name": name,
        "email": email,
        "password": password,
        "phone": phone or None,
        "date_of_birth": date_of_birth or None,
        "emergency_contact": emergency_contact or None,
    }
    client = BackendClient()
    try:
        await client.post("/auth/register", json=payload)
    except BackendAPIError as exc:
        return render(request, "register.html", {"error": exc.detail})

    message = quote("Account created — please log in.")
    return RedirectResponse(f"/login?msg={message}", status_code=303)


@router.get("/logout")
async def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie("access_token")
    response.delete_cookie("refresh_token")
    return response
