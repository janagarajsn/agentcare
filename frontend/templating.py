from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def render(request: Request, template_name: str, context: dict | None = None):
    context = context or {}
    context.setdefault("request", request)
    context.setdefault("flash_message", request.query_params.get("msg"))
    context.setdefault("flash_type", request.query_params.get("msg_type", "success"))
    context.setdefault("user", getattr(request.state, "user", None))
    return templates.TemplateResponse(request, template_name, context)
