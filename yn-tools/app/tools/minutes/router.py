"""議事録ツール - ルーター"""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from app.core.templates import make_templates
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_tool_access
from app.database import get_db
from app.users.models import User

from .models import MinutesHistory
from . import service
from app.tools.usage_limit import get_monthly_usage, get_limit, limit_error

router = APIRouter(prefix="/tools/minutes", tags=["minutes"])
templates = make_templates("app/templates")


@router.get("/", response_class=HTMLResponse)
async def minutes_index(
    request: Request,
    user: User = Depends(require_tool_access("minutes")),
    db: AsyncSession = Depends(get_db),
):
    """議事録ツール ダッシュボード"""
    stats = await db.execute(
        select(
            func.count(MinutesHistory.id),
            func.coalesce(func.sum(MinutesHistory.input_chars), 0),
        ).where(MinutesHistory.user_id == user.id)
    )
    row = stats.one()

    recent = await db.execute(
        select(MinutesHistory)
        .where(MinutesHistory.user_id == user.id)
        .order_by(MinutesHistory.created_at.desc())
        .limit(10)
    )
    history = recent.scalars().all()

    monthly_used = await get_monthly_usage(db, user.id, "minutes")

    return templates.TemplateResponse(
        request, "tools/minutes/index.html", {
            "user": user,
            "page": "minutes",
            "total_uses": row[0],
            "total_chars": row[1],
            "history": history,
            "monthly_used": monthly_used,
            "monthly_limit": get_limit("minutes"),
        }
    )


@router.post("/api/process")
async def api_process(
    request: Request,
    user: User = Depends(require_tool_access("minutes")),
    db: AsyncSession = Depends(get_db),
    text: str = Form(default=""),
    title: str = Form(default=""),
    action: str = Form(default="generate"),
):
    """議事録処理API"""
    if not text.strip():
        return {"error": "会議のメモやテキストを入力してください。"}

    used = await get_monthly_usage(db, user.id, "minutes")
    if err := limit_error("minutes", used, get_limit("minutes")):
        return {"error": err}

    try:
        result = await service.process_minutes(text.strip(), action, title.strip())
    except ValueError as e:
        return {"error": str(e)}

    history = MinutesHistory(
        user_id=user.id,
        title=title[:255] if title else None,
        action=action,
        input_chars=len(text),
        output_chars=len(result),
        result_preview=result[:200],
    )
    db.add(history)
    await db.commit()

    return {"result": result, "input_chars": len(text), "output_chars": len(result)}
