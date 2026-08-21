"""AI議事メモ（音声） - ルーター"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from app.core.templates import make_templates

from app.auth.dependencies import require_tool_access
from app.users.models import User

router = APIRouter(prefix="/tools/voiceminutes", tags=["voiceminutes"])
templates = make_templates("app/templates")


@router.get("/", response_class=HTMLResponse)
async def voiceminutes_index(
    request: Request,
    user: User = Depends(require_tool_access("voiceminutes")),
):
    """AI議事メモ（音声）"""
    return templates.TemplateResponse(
        request, "tools/voiceminutes/index.html", {
            "user": user,
            "page": "voiceminutes",
        }
    )
