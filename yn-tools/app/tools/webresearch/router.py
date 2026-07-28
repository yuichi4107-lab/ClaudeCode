"""AI Webリサーチャー - ルーター"""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from app.core.templates import make_templates
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_tool_access
from app.database import get_db
from app.users.models import User

from .models import WebResearchHistory
from . import service
from app.tools.usage_limit import get_monthly_usage, get_limit, limit_error

router = APIRouter(prefix="/tools/webresearch", tags=["webresearch"])
templates = make_templates("app/templates")


# ---------- UI ----------

@router.get("/", response_class=HTMLResponse)
async def webresearch_index(
    request: Request,
    user: User = Depends(require_tool_access("webresearch")),
    db: AsyncSession = Depends(get_db),
):
    """AI Webリサーチャー ダッシュボード"""
    stats = await db.execute(
        select(func.count(WebResearchHistory.id))
        .where(WebResearchHistory.user_id == user.id)
    )
    total_uses = stats.scalar() or 0

    recent = await db.execute(
        select(WebResearchHistory)
        .where(WebResearchHistory.user_id == user.id)
        .order_by(WebResearchHistory.created_at.desc())
        .limit(10)
    )
    history = recent.scalars().all()
    monthly_used = await get_monthly_usage(db, user.id, "webresearch")

    return templates.TemplateResponse(
        request, "tools/webresearch/index.html", {
            "user": user,
            "page": "webresearch",
            "total_uses": total_uses,
            "history": history,
            "monthly_used": monthly_used,
            "monthly_limit": get_limit("webresearch"),
        }
    )


# ---------- 単一ページ分析 API ----------

@router.post("/api/analyze")
async def api_analyze(
    user: User = Depends(require_tool_access("webresearch")),
    db: AsyncSession = Depends(get_db),
    url: str = Form(default=""),
    analysis_type: str = Form(default="summary"),
):
    """単一ページをAI分析"""
    if not url.strip():
        return {"error": "URLを入力してください。"}

    used = await get_monthly_usage(db, user.id, "webresearch")
    if err := limit_error("webresearch", used, get_limit("webresearch")):
        return {"error": err}

    try:
        page = await service.fetch_page(url.strip())
    except Exception as e:
        return {"error": f"ページ取得に失敗しました: {e}"}

    try:
        result = await service.analyze_page(
            text=page["text"],
            title=page["title"],
            url=page["url"],
            analysis_type=analysis_type,
        )
    except Exception as e:
        return {"error": f"AI分析に失敗しました: {e}"}

    history = WebResearchHistory(
        user_id=user.id,
        action="analyze",
        url=page["url"][:2000],
        title=page["title"][:500] if page["title"] else None,
        output_chars=len(result),
        result_preview=result[:200],
    )
    db.add(history)
    await db.commit()

    return {
        "result": result,
        "page_title": page["title"],
        "page_url": page["url"],
        "meta_description": page["meta_description"],
        "links_count": len(page.get("links", [])),
        "text_length": len(page["text"]),
    }


# ---------- 複数ページ比較 API ----------

@router.post("/api/compare")
async def api_compare(
    user: User = Depends(require_tool_access("webresearch")),
    db: AsyncSession = Depends(get_db),
    urls: str = Form(default=""),
):
    """複数ページの比較分析"""
    url_list = [u.strip() for u in urls.strip().splitlines() if u.strip()]
    if len(url_list) < 2:
        return {"error": "比較するには2つ以上のURLを入力してください（1行に1URL）。"}
    if len(url_list) > 5:
        return {"error": "一度に比較できるのは最大5サイトです。"}

    used = await get_monthly_usage(db, user.id, "webresearch")
    if err := limit_error("webresearch", used, get_limit("webresearch")):
        return {"error": err}

    pages = await service.fetch_multiple_pages(url_list)

    try:
        result = await service.compare_pages(pages)
    except Exception as e:
        return {"error": f"AI分析に失敗しました: {e}"}

    # 履歴保存（最初のURLで記録）
    history = WebResearchHistory(
        user_id=user.id,
        action="compare",
        url=", ".join(url_list)[:2000],
        title=f"{len(url_list)}サイト比較",
        output_chars=len(result),
        result_preview=result[:200],
    )
    db.add(history)
    await db.commit()

    return {
        "result": result,
        "pages": [
            {"url": p.get("url", ""), "title": p.get("title", ""), "error": p.get("error")}
            for p in pages
        ],
    }
