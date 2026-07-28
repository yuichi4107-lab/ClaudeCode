"""契約書チェッカー - ルーター"""

from fastapi import APIRouter, Depends, Form, Request, UploadFile
from fastapi.responses import HTMLResponse
from app.core.templates import make_templates
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_tool_access
from app.database import get_db
from app.users.models import User

from .models import ContractHistory
from . import service
from app.tools.usage_limit import get_monthly_usage, get_limit, limit_error

router = APIRouter(prefix="/tools/contract", tags=["contract"])
templates = make_templates("app/templates")


@router.get("/", response_class=HTMLResponse)
async def contract_index(
    request: Request,
    user: User = Depends(require_tool_access("contract")),
    db: AsyncSession = Depends(get_db),
):
    """契約書チェッカー ダッシュボード"""
    stats = await db.execute(
        select(
            func.count(ContractHistory.id),
            func.coalesce(func.sum(ContractHistory.input_chars), 0),
        ).where(ContractHistory.user_id == user.id)
    )
    row = stats.one()
    total_uses = row[0]
    total_chars = row[1]

    recent = await db.execute(
        select(ContractHistory)
        .where(ContractHistory.user_id == user.id)
        .order_by(ContractHistory.created_at.desc())
        .limit(10)
    )
    history = recent.scalars().all()

    monthly_used = await get_monthly_usage(db, user.id, "contract")

    return templates.TemplateResponse(
        request, "tools/contract/index.html", {
            "user": user,
            "page": "contract",
            "total_uses": total_uses,
            "total_chars": total_chars,
            "history": history,
            "monthly_used": monthly_used,
            "monthly_limit": get_limit("contract"),
        }
    )


@router.post("/api/check")
async def api_check(
    request: Request,
    user: User = Depends(require_tool_access("contract")),
    db: AsyncSession = Depends(get_db),
    file: UploadFile | None = None,
    text: str = Form(default=""),
    check_type: str = Form(default="risk"),
):
    """契約書チェックAPI"""
    # ファイルまたはテキストから入力取得
    if file and file.filename:
        content = await file.read()
        if not content:
            return {"error": "ファイルが空です。"}
        if len(content) > 10 * 1024 * 1024:
            return {"error": "ファイルサイズが上限（10MB）を超えています。"}
        try:
            input_text = await service.extract_text_from_file(content, file.filename)
        except ValueError as e:
            return {"error": str(e)}
    elif text.strip():
        input_text = text.strip()
    else:
        return {"error": "契約書のテキストまたはファイルを入力してください。"}

    used = await get_monthly_usage(db, user.id, "contract")
    if err := limit_error("contract", used, get_limit("contract")):
        return {"error": err}

    try:
        result = await service.check_contract(input_text, check_type)
    except ValueError as e:
        return {"error": str(e)}

    history = ContractHistory(
        user_id=user.id,
        check_type=check_type,
        filename=file.filename if file and file.filename else None,
        input_chars=len(input_text),
        output_chars=len(result),
        result_preview=result[:200],
    )
    db.add(history)
    await db.commit()

    return {"result": result, "input_chars": len(input_text), "output_chars": len(result)}
