"""日報ジェネレーター - ルーター"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from app.core.templates import make_templates

from app.auth.dependencies import require_tool_access
from app.users.models import User

router = APIRouter(prefix="/tools/dailyreport", tags=["dailyreport"])
templates = make_templates("app/templates")


@router.get("/", response_class=HTMLResponse)
async def dailyreport_index(
    request: Request,
    user: User = Depends(require_tool_access("dailyreport")),
):
    """日報ジェネレーター"""
    return templates.TemplateResponse(
        request, "tools/dailyreport/index.html", {
            "user": user,
            "page": "dailyreport",
        }
    )
