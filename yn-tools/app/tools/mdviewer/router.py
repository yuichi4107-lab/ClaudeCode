from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from app.core.templates import make_templates

from app.auth.dependencies import require_tool_access
from app.users.models import User

router = APIRouter(prefix="/tools/mdviewer", tags=["mdviewer"])
templates = make_templates("app/templates")


@router.get("/", response_class=HTMLResponse)
async def mdviewer_index(
    request: Request,
    user: User = Depends(require_tool_access("mdviewer")),
):
    """Markdownビューアー"""
    return templates.TemplateResponse(
        request, "tools/mdviewer/index.html", {
            "user": user,
            "page": "mdviewer",
        }
    )
