"""売上ダッシュボード - ルーター"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from app.core.templates import make_templates

from app.auth.dependencies import require_tool_access
from app.users.models import User

router = APIRouter(prefix="/tools/salesboard", tags=["salesboard"])
templates = make_templates("app/templates")


@router.get("/", response_class=HTMLResponse)
async def salesboard_index(
    request: Request,
    user: User = Depends(require_tool_access("salesboard")),
):
    """売上ダッシュボード"""
    return templates.TemplateResponse(
        request, "tools/salesboard/index.html", {
            "user": user,
            "page": "salesboard",
        }
    )
