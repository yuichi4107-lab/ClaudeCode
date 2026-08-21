"""翻訳ツール - ルーター"""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from app.core.templates import make_templates
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_tool_access
from app.database import get_db
from app.users.models import User

from .models import TranslateHistory
from . import service
from app.tools.usage_limit import get_monthly_usage, get_limit, limit_error

router = APIRouter(prefix="/tools/translate", tags=["translate"])
templates = make_templates("app/templates")


@router.get("/", response_class=HTMLResponse)
async def translate_index(
    request: Request,
    user: User = Depends(require_tool_access("translate")),
    db: AsyncSession = Depends(get_db),
):
    """翻訳ツール ダッシュボード"""
    stats = await db.execute(
        select(
            func.count(TranslateHistory.id),
            func.coalesce(func.sum(TranslateHistory.input_chars), 0),
        ).where(TranslateHistory.user_id == user.id)
    )
    row = stats.one()
    total_uses = row[0]
    total_chars = row[1]

    recent = await db.execute(
        select(TranslateHistory)
        .where(TranslateHistory.user_id == user.id)
        .order_by(TranslateHistory.created_at.desc())
        .limit(10)
    )
    history = recent.scalars().all()

    monthly_used = await get_monthly_usage(db, user.id, "translate")

    return templates.TemplateResponse(
        request, "tools/translate/index.html", {
            "user": user,
            "page": "translate",
            "total_uses": total_uses,
            "total_chars": total_chars,
            "history": history,
            "monthly_used": monthly_used,
            "monthly_limit": get_limit("translate"),
            "languages": service.LANG_MAP,
        }
    )


@router.post("/api/translate")
async def api_translate(
    request: Request,
    user: User = Depends(require_tool_access("translate")),
    db: AsyncSession = Depends(get_db),
    text: str = Form(default=""),
    source_lang: str = Form(default="auto"),
    target_lang: str = Form(default="en"),
    tone: str = Form(default="natural"),
):
    """翻訳API"""
    if not text.strip():
        return {"error": "翻訳するテキストを入力してください。"}

    used = await get_monthly_usage(db, user.id, "translate")
    if err := limit_error("translate", used, get_limit("translate")):
        return {"error": err}

    try:
        result = await service.translate(text.strip(), source_lang, target_lang, tone)
    except ValueError as e:
        return {"error": str(e)}

    history = TranslateHistory(
        user_id=user.id,
        source_lang=source_lang,
        target_lang=target_lang,
        input_chars=len(text),
        output_chars=len(result),
        result_preview=result[:200],
    )
    db.add(history)
    await db.commit()

    return {"result": result, "input_chars": len(text), "output_chars": len(result)}
