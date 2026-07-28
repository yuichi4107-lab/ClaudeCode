"""SNS投稿スケジューラー - ルーター"""

from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from app.core.templates import make_templates
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_tool_access
from app.database import get_db
from app.users.models import User

from .models import SnsPost
from . import service

router = APIRouter(prefix="/tools/sns", tags=["sns"])
templates = make_templates("app/templates")


@router.get("/", response_class=HTMLResponse)
async def sns_index(
    request: Request,
    user: User = Depends(require_tool_access("sns")),
    db: AsyncSession = Depends(get_db),
):
    """SNS投稿スケジューラー"""
    # Stats
    stats = await db.execute(
        select(func.count(SnsPost.id)).where(SnsPost.user_id == user.id)
    )
    total_posts = stats.scalar() or 0

    # All posts
    result = await db.execute(
        select(SnsPost)
        .where(SnsPost.user_id == user.id)
        .order_by(SnsPost.scheduled_at.desc().nullslast(), SnsPost.created_at.desc())
        .limit(50)
    )
    posts = result.scalars().all()

    return templates.TemplateResponse(
        request, "tools/sns/index.html", {
            "user": user,
            "page": "sns",
            "total_posts": total_posts,
            "posts": posts,
            "platforms": service.PLATFORMS,
        }
    )


@router.post("/api/create")
async def api_create(
    user: User = Depends(require_tool_access("sns")),
    db: AsyncSession = Depends(get_db),
    platform: str = Form(default="x"),
    content: str = Form(default=""),
    hashtags: str = Form(default=""),
    scheduled_at: str = Form(default=""),
    status: str = Form(default="draft"),
):
    """投稿作成"""
    if not content.strip():
        return {"error": "投稿内容を入力してください。"}

    sched = None
    if scheduled_at:
        try:
            sched = datetime.fromisoformat(scheduled_at)
        except ValueError:
            return {"error": "日時の形式が正しくありません。"}

    post = SnsPost(
        user_id=user.id,
        platform=platform,
        content=content.strip(),
        hashtags=hashtags.strip() or None,
        scheduled_at=sched,
        status="scheduled" if sched else status,
    )
    db.add(post)
    await db.commit()
    return {"ok": True, "id": post.id}


@router.post("/api/update/{post_id}")
async def api_update(
    post_id: int,
    user: User = Depends(require_tool_access("sns")),
    db: AsyncSession = Depends(get_db),
    content: str = Form(default=""),
    hashtags: str = Form(default=""),
    scheduled_at: str = Form(default=""),
    status: str = Form(default="draft"),
):
    """投稿更新"""
    result = await db.execute(
        select(SnsPost).where(SnsPost.id == post_id, SnsPost.user_id == user.id)
    )
    post = result.scalar_one_or_none()
    if not post:
        return {"error": "投稿が見つかりません。"}

    if content.strip():
        post.content = content.strip()
    post.hashtags = hashtags.strip() or None
    post.status = status

    if scheduled_at:
        try:
            post.scheduled_at = datetime.fromisoformat(scheduled_at)
            if status == "draft":
                post.status = "scheduled"
        except ValueError:
            pass

    await db.commit()
    return {"ok": True}


@router.post("/api/delete/{post_id}")
async def api_delete(
    post_id: int,
    user: User = Depends(require_tool_access("sns")),
    db: AsyncSession = Depends(get_db),
):
    """投稿削除"""
    result = await db.execute(
        select(SnsPost).where(SnsPost.id == post_id, SnsPost.user_id == user.id)
    )
    post = result.scalar_one_or_none()
    if not post:
        return {"error": "投稿が見つかりません。"}
    await db.delete(post)
    await db.commit()
    return {"ok": True}


@router.post("/api/generate")
async def api_generate(
    user: User = Depends(require_tool_access("sns")),
    topic: str = Form(default=""),
    platform: str = Form(default="x"),
    tone: str = Form(default="casual"),
):
    """AI文案生成"""
    try:
        result = await service.generate_post(topic, platform, tone)
    except ValueError as e:
        return {"error": str(e)}
    return result
