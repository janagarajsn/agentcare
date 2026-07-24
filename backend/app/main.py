import logging

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import (
    routes_appointments,
    routes_auth,
    routes_documents,
    routes_escalations,
    routes_patient,
    routes_staff,
    routes_workflows,
)
from app.config import get_settings

logger = logging.getLogger("agentcare")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(title="AgentCare", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Internal server error"},
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=exc.headers,
        )

    app.include_router(routes_auth.router)
    app.include_router(routes_staff.router)
    app.include_router(routes_patient.router)
    app.include_router(routes_appointments.router)
    app.include_router(routes_documents.router)
    app.include_router(routes_workflows.router)
    app.include_router(routes_escalations.router)

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
