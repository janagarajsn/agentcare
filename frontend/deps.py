from fastapi import Request

from backend_client import BackendAPIError, BackendClient


class AuthRedirect(Exception):
    def __init__(self, location: str = "/login"):
        self.location = location
        super().__init__(location)


async def get_current_user(request: Request) -> dict:
    token = request.cookies.get("access_token")
    if not token:
        raise AuthRedirect("/login")

    client = BackendClient(token)
    try:
        user = await client.get("/auth/me")
    except BackendAPIError:
        raise AuthRedirect("/login?error=session_expired")

    user["_token"] = token
    request.state.user = user
    return user


async def get_current_user_optional(request: Request) -> dict | None:
    """Like get_current_user, but returns None instead of raising — for
    routes (/, /login, /register) that need to check whether a session
    already exists without forcing one."""
    token = request.cookies.get("access_token")
    if not token:
        return None

    client = BackendClient(token)
    try:
        user = await client.get("/auth/me")
    except BackendAPIError:
        return None

    user["_token"] = token
    request.state.user = user
    return user


def dashboard_path(user: dict) -> str:
    return "/patient/dashboard" if user["role"] == "patient" else "/staff/dashboard"


async def require_patient(request: Request) -> dict:
    user = await get_current_user(request)
    if user["role"] != "patient":
        raise AuthRedirect("/login?error=patient_only")
    return user


async def require_staff(request: Request) -> dict:
    user = await get_current_user(request)
    if user["role"] not in ("staff", "admin"):
        raise AuthRedirect("/login?error=staff_only")
    return user
