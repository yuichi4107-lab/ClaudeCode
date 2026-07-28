"""AIコンテンツ生成ツール - ルーター"""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from app.core.templates import make_templates
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_tool_access
from app.database import get_db
from app.users.models import User

from .models import ContentGenHistory, ContentTemplate
from . import service
from app.tools.usage_limit import get_monthly_usage, get_limit, limit_error

router = APIRouter(prefix="/tools/contentgen", tags=["contentgen"])
templates = make_templates("app/templates")


# ---------- UI ページ ----------

@router.get("/", response_class=HTMLResponse)
async def contentgen_index(
    request: Request,
    user: User = Depends(require_tool_access("contentgen")),
    db: AsyncSession = Depends(get_db),
):
    """AIコンテンツ生成 ダッシュボード"""
    stats = await db.execute(
        select(
            func.count(ContentGenHistory.id),
            func.coalesce(func.sum(ContentGenHistory.output_chars), 0),
        ).where(ContentGenHistory.user_id == user.id)
    )
    row = stats.one()
    total_uses = row[0]
    total_chars = row[1]

    recent = await db.execute(
        select(ContentGenHistory)
        .where(ContentGenHistory.user_id == user.id)
        .order_by(ContentGenHistory.created_at.desc())
        .limit(10)
    )
    history = recent.scalars().all()

    # ユーザーカスタムテンプレート
    user_templates = await db.execute(
        select(ContentTemplate)
        .where(ContentTemplate.user_id == user.id)
        .order_by(ContentTemplate.created_at.desc())
    )
    custom_templates = user_templates.scalars().all()

    monthly_used = await get_monthly_usage(db, user.id, "contentgen")

    return templates.TemplateResponse(
        request, "tools/contentgen/index.html", {
            "user": user,
            "page": "contentgen",
            "total_uses": total_uses,
            "total_chars": total_chars,
            "history": history,
            "builtin_templates": service.BUILTIN_TEMPLATES,
            "custom_templates": custom_templates,
            "monthly_used": monthly_used,
            "monthly_limit": get_limit("contentgen"),
        }
    )


# ---------- コンテンツ生成 API ----------

@router.post("/api/generate")
async def api_generate(
    request: Request,
    user: User = Depends(require_tool_access("contentgen")),
    db: AsyncSession = Depends(get_db),
    template_key: str = Form(default="free_custom"),
    topic: str = Form(default=""),
    target: str = Form(default=""),
    tone: str = Form(default=""),
    usp: str = Form(default=""),
    length: str = Form(default="1000"),
):
    """コンテンツ生成"""
    if not topic.strip():
        return {"error": "テーマ/トピックを入力してください。"}

    used = await get_monthly_usage(db, user.id, "contentgen")
    if err := limit_error("contentgen", used, get_limit("contentgen")):
        return {"error": err}

    try:
        result = await service.generate_content(
            template_key=template_key,
            topic=topic.strip(),
            target=target.strip(),
            tone=tone.strip(),
            usp=usp.strip(),
            length=length.strip(),
        )
    except ValueError as e:
        return {"error": str(e)}

    # テンプレート情報取得
    tmpl = service.BUILTIN_TEMPLATES.get(template_key, {})
    content_type = tmpl.get("content_type", "free")
    platform = template_key.replace("sns_", "").replace("email_", "").replace("blog_", "").replace("ad_", "") if "_" in template_key else None

    history = ContentGenHistory(
        user_id=user.id,
        content_type=content_type,
        platform=platform,
        topic=topic[:500],
        output_chars=len(result),
        result_preview=result[:200],
    )
    db.add(history)
    await db.commit()

    return {"result": result, "output_chars": len(result)}


# ---------- テンプレート管理 API ----------

@router.post("/api/templates/save")
async def api_save_template(
    user: User = Depends(require_tool_access("contentgen")),
    db: AsyncSession = Depends(get_db),
    name: str = Form(default=""),
    content_type: str = Form(default="free"),
    system_prompt: str = Form(default=""),
    user_prompt_template: str = Form(default=""),
):
    """カスタムテンプレート保存"""
    if not name.strip() or not system_prompt.strip():
        return {"error": "テンプレート名とシステムプロンプトは必須です。"}

    tmpl = ContentTemplate(
        user_id=user.id,
        name=name.strip(),
        content_type=content_type,
        system_prompt=system_prompt.strip(),
        user_prompt_template=user_prompt_template.strip() or "{topic}",
    )
    db.add(tmpl)
    await db.commit()
    return {"ok": True, "id": tmpl.id}


@router.post("/api/templates/delete/{template_id}")
async def api_delete_template(
    template_id: int,
    user: User = Depends(require_tool_access("contentgen")),
    db: AsyncSession = Depends(get_db),
):
    """カスタムテンプレート削除"""
    result = await db.execute(
        select(ContentTemplate).where(
            ContentTemplate.id == template_id,
            ContentTemplate.user_id == user.id,
        )
    )
    tmpl = result.scalar_one_or_none()
    if not tmpl:
        return {"error": "テンプレートが見つかりません。"}
    await db.delete(tmpl)
    await db.commit()
    return {"ok": True}


# ---------- 組み込みテンプレート一覧 API ----------

@router.get("/api/templates")
async def api_list_templates(
    user: User = Depends(require_tool_access("contentgen")),
):
    """組み込みテンプレート一覧"""
    return {
        key: {"name": v["name"], "content_type": v["content_type"]}
        for key, v in service.BUILTIN_TEMPLATES.items()
    }
