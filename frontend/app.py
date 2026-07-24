import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from backend_client import BackendAPIError
from deps import AuthRedirect, dashboard_path, get_current_user_optional
from routers import auth, patient, staff
from templating import render

BASE_DIR = Path(__file__).resolve().parent
logger = logging.getLogger("agentcare.frontend")


def create_app() -> FastAPI:
    app = FastAPI(title="AgentCare Frontend")

    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

    @app.exception_handler(AuthRedirect)
    async def handle_auth_redirect(request: Request, exc: AuthRedirect) -> RedirectResponse:
        return RedirectResponse(exc.location, status_code=303)

    @app.exception_handler(BackendAPIError)
    async def handle_backend_api_error(request: Request, exc: BackendAPIError):
        # Safety net for any route that doesn't catch this explicitly —
        # show a friendly page instead of a raw crash.
        return render(request, "error.html", {"message": exc.detail})

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception):
        logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
        return render(
            request,
            "error.html",
            {"message": "An unexpected error occurred. Please try again."},
        )

    app.include_router(auth.router)
    app.include_router(patient.router)
    app.include_router(staff.router)

    @app.get("/")
    async def index(request: Request) -> RedirectResponse:
        user = await get_current_user_optional(request)
        destination = dashboard_path(user) if user else "/login"
        return RedirectResponse(destination, status_code=303)

    return app


app = create_app()
