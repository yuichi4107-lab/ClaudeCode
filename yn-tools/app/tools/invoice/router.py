"""請求書ジェネレーター - ルーター"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from app.core.templates import make_templates

from app.auth.dependencies import require_tool_access
from app.users.models import User

router = APIRouter(prefix="/tools/invoice", tags=["invoice"])
templates = make_templates("app/templates")


@router.get("/", response_class=HTMLResponse)
async def invoice_index(
    request: Request,
    user: User = Depends(require_tool_access("invoice")),
):
    """請求書ジェネレーター"""
    return templates.TemplateResponse(
        request, "tools/invoice/index.html", {
            "user": user,
            "page": "invoice",
        }
    )
