"""ファイル変換ツール - クライアントサイド変換"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from app.core.templates import make_templates

from app.auth.dependencies import require_tool_access
from app.users.models import User

router = APIRouter(prefix="/tools/fileconv", tags=["fileconv"])
templates = make_templates("app/templates")


@router.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    user: User = Depends(require_tool_access("fileconv")),
):
    return templates.TemplateResponse(
        request, "tools/fileconv/index.html",
        {"user": user, "page": "fileconv"},
    )
