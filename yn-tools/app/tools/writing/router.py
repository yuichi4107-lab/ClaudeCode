"""ライティングアシスタント - ルーター"""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from app.core.templates import make_templates
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_tool_access
from app.database import get_db
from app.users.models import User

from .models import WritingHistory
from . import service
from app.tools.usage_limit import get_monthly_usage, get_limit, limit_error

router = APIRouter(prefix="/tools/writing", tags=["writing"])
templates = make_templates("app/templates")


@router.get("/", response_class=HTMLResponse)
async def writing_index(
    request: Request,
    user: User = Depends(require_tool_access("writing")),
    db: AsyncSession = Depends(get_db),
):
    """ライティングアシスタント ダッシュボード"""
    stats = await db.execute(
        select(
            func.count(WritingHistory.id),
            func.coalesce(func.sum(WritingHistory.input_chars), 0),
        ).where(WritingHistory.user_id == user.id)
    )
    row = stats.one()
    total_uses = row[0]
    total_chars = row[1]

    recent = await db.execute(
        select(WritingHistory)
        .where(WritingHistory.user_id == user.id)
        .order_by(WritingHistory.created_at.desc())
        .limit(10)
    )
    history = recent.scalars().all()

    monthly_used = await get_monthly_usage(db, user.id, "writing")

    return templates.TemplateResponse(
        request, "tools/writing/index.html", {
            "user": user,
            "page": "writing",
            "total_uses": total_uses,
            "total_chars": total_chars,
            "history": history,
            "monthly_used": monthly_used,
            "monthly_limit": get_limit("writing"),
            "actions": service.ACTIONS,
        }
    )


@router.post("/api/process")
async def api_process(
    request: Request,
    user: User = Depends(require_tool_access("writing")),
    db: AsyncSession = Depends(get_db),
    text: str = Form(default=""),
    action: str = Form(default="proofread"),
    tone: str = Form(default=""),
):
    """ライティング処理API"""
    if not text.strip():
        return {"error": "テキストを入力してください。"}

    used = await get_monthly_usage(db, user.id, "writing")
    if err := limit_error("writing", used, get_limit("writing")):
        return {"error": err}

    try:
        result = await service.process(text.strip(), action, tone)
    except ValueError as e:
        return {"error": str(e)}

    history = WritingHistory(
        user_id=user.id,
        action=action,
        input_chars=len(text),
        output_chars=len(result),
        result_preview=result[:200],
    )
    db.add(history)
    await db.commit()

    return {"result": result, "input_chars": len(text), "output_chars": len(result)}
