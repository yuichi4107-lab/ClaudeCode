"""AI文書処理ツール - ルーター"""

from fastapi import APIRouter, Depends, Form, Request, UploadFile
from fastapi.responses import HTMLResponse
from app.core.templates import make_templates
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_tool_access
from app.database import get_db
from app.users.models import User

from .models import DocaiHistory
from . import service
from app.tools.usage_limit import get_monthly_usage, get_limit, limit_error

router = APIRouter(prefix="/tools/docai", tags=["docai"])
templates = make_templates("app/templates")


# ---------- UI ページ ----------

@router.get("/", response_class=HTMLResponse)
async def docai_index(
    request: Request,
    user: User = Depends(require_tool_access("docai")),
    db: AsyncSession = Depends(get_db),
):
    """AI文書処理 ダッシュボード"""
    # 利用統計
    stats = await db.execute(
        select(
            func.count(DocaiHistory.id),
            func.coalesce(func.sum(DocaiHistory.input_chars), 0),
        ).where(DocaiHistory.user_id == user.id)
    )
    row = stats.one()
    total_uses = row[0]
    total_chars = row[1]

    # 最近の履歴
    recent = await db.execute(
        select(DocaiHistory)
        .where(DocaiHistory.user_id == user.id)
        .order_by(DocaiHistory.created_at.desc())
        .limit(10)
    )
    history = recent.scalars().all()

    monthly_used = await get_monthly_usage(db, user.id, "docai")

    return templates.TemplateResponse(
        request, "tools/docai/index.html", {
            "user": user,
            "page": "docai",
            "total_uses": total_uses,
            "total_chars": total_chars,
            "history": history,
            "monthly_used": monthly_used,
            "monthly_limit": get_limit("docai"),
        }
    )


# ---------- API エンドポイント ----------

@router.post("/api/summarize")
async def api_summarize(
    request: Request,
    user: User = Depends(require_tool_access("docai")),
    db: AsyncSession = Depends(get_db),
    file: UploadFile | None = None,
    text: str = Form(default=""),
    lang: str = Form(default="ja"),
    detail: str = Form(default="normal"),
):
    """文書要約API"""
    input_text = await _resolve_input(file, text)

    used = await get_monthly_usage(db, user.id, "docai")
    if err := limit_error("docai", used, get_limit("docai")):
        return {"error": err}

    try:
        result = await service.summarize(input_text, lang=lang, detail=detail)
    except ValueError as e:
        return {"error": str(e)}

    await _save_history(db, user.id, "summarize", file, input_text, result)
    return {"result": result, "input_chars": len(input_text), "output_chars": len(result)}


@router.post("/api/translate")
async def api_translate(
    request: Request,
    user: User = Depends(require_tool_access("docai")),
    db: AsyncSession = Depends(get_db),
    file: UploadFile | None = None,
    text: str = Form(default=""),
    target_lang: str = Form(default="en"),
):
    """翻訳API"""
    input_text = await _resolve_input(file, text)

    used = await get_monthly_usage(db, user.id, "docai")
    if err := limit_error("docai", used, get_limit("docai")):
        return {"error": err}

    try:
        result = await service.translate(input_text, target_lang=target_lang)
    except ValueError as e:
        return {"error": str(e)}

    await _save_history(db, user.id, "translate", file, input_text, result)
    return {"result": result, "input_chars": len(input_text), "output_chars": len(result)}


@router.post("/api/qa")
async def api_qa(
    request: Request,
    user: User = Depends(require_tool_access("docai")),
    db: AsyncSession = Depends(get_db),
    file: UploadFile | None = None,
    text: str = Form(default=""),
    question: str = Form(default=""),
):
    """文書Q&A API"""
    input_text = await _resolve_input(file, text)

    if not question.strip():
        return {"error": "質問を入力してください。"}

    used = await get_monthly_usage(db, user.id, "docai")
    if err := limit_error("docai", used, get_limit("docai")):
        return {"error": err}

    try:
        result = await service.qa(input_text, question)
    except ValueError as e:
        return {"error": str(e)}

    await _save_history(db, user.id, "qa", file, input_text, result)
    return {"result": result, "input_chars": len(input_text), "output_chars": len(result)}


@router.post("/api/extract")
async def api_extract(
    request: Request,
    user: User = Depends(require_tool_access("docai")),
    db: AsyncSession = Depends(get_db),
    file: UploadFile | None = None,
    text: str = Form(default=""),
    extract_type: str = Form(default="key_points"),
):
    """情報抽出API"""
    input_text = await _resolve_input(file, text)

    used = await get_monthly_usage(db, user.id, "docai")
    if err := limit_error("docai", used, get_limit("docai")):
        return {"error": err}

    try:
        result = await service.extract_info(input_text, extract_type=extract_type)
    except ValueError as e:
        return {"error": str(e)}

    await _save_history(db, user.id, "extract", file, input_text, result)
    return {"result": result, "input_chars": len(input_text), "output_chars": len(result)}


# ---------- 履歴API ----------

@router.get("/api/history")
async def api_history(
    user: User = Depends(require_tool_access("docai")),
    db: AsyncSession = Depends(get_db),
):
    """利用履歴取得"""
    result = await db.execute(
        select(DocaiHistory)
        .where(DocaiHistory.user_id == user.id)
        .order_by(DocaiHistory.created_at.desc())
        .limit(50)
    )
    items = result.scalars().all()
    return [
        {
            "id": h.id,
            "action": h.action,
            "filename": h.filename,
            "input_chars": h.input_chars,
            "output_chars": h.output_chars,
            "result_preview": h.result_preview,
            "created_at": h.created_at.isoformat() if h.created_at else None,
        }
        for h in items
    ]


# ---------- 内部ヘルパー ----------

async def _resolve_input(file: UploadFile | None, text: str) -> str:
    """ファイルまたはテキスト入力からテキストを取得"""
    if file and file.filename:
        content = await file.read()
        if not content:
            raise ValueError("ファイルが空です。")
        if len(content) > 10 * 1024 * 1024:
            raise ValueError("ファイルサイズが上限（10MB）を超えています。")
        return await service.extract_text_from_file(content, file.filename)
    if text.strip():
        return text.strip()
    raise ValueError("テキストまたはファイルを入力してください。")


async def _save_history(
    db: AsyncSession, user_id: int, action: str,
    file: UploadFile | None, input_text: str, result: str,
):
    """処理履歴を保存"""
    history = DocaiHistory(
        user_id=user_id,
        action=action,
        filename=file.filename if file and file.filename else None,
        input_chars=len(input_text),
        output_chars=len(result),
        result_preview=result[:200],
    )
    db.add(history)
    await db.commit()
