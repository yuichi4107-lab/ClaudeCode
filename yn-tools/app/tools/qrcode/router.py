"""QRコードジェネレーター - クライアントサイド生成"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from app.core.templates import make_templates

from app.auth.dependencies import require_tool_access
from app.users.models import User

router = APIRouter(prefix="/tools/qrcode", tags=["qrcode"])
templates = make_templates("app/templates")


@router.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    user: User = Depends(require_tool_access("qrcode")),
):
    return templates.TemplateResponse(
        request, "tools/qrcode/index.html",
        {"user": user, "page": "qrcode"},
    )
