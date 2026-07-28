"""Shared Jinja2Templates factory that injects DEMO_MODE globally."""

from fastapi.templating import Jinja2Templates

from app.config import settings


def make_templates(directory: str = "app/templates") -> Jinja2Templates:
    t = Jinja2Templates(directory=directory)
    t.env.globals["demo_mode"] = settings.demo_mode
    return t
