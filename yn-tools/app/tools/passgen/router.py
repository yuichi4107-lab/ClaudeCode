"""パスワード生成 - ルーター"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from app.core.templates import make_templates

from app.auth.dependencies import require_tool_access
from app.users.models import User

router = APIRouter(prefix="/tools/passgen", tags=["passgen"])
templates = make_templates("app/templates")


@router.get("/", response_class=HTMLResponse)
async def passgen_index(
    request: Request,
    user: User = Depends(require_tool_access("passgen")),
):
    """パスワード生成"""
    return templates.TemplateResponse(
        request, "tools/passgen/index.html", {
            "user": user,
            "page": "passgen",
        }
    )
