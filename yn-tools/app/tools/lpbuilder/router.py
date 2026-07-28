"""LPビルダー - ルーター"""

import json
import re

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from app.core.templates import make_templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_tool_access, get_current_user
from app.database import get_db
from app.users.models import User

from .models import LandingPage

router = APIRouter(prefix="/tools/lpbuilder", tags=["lpbuilder"])
templates = make_templates("app/templates")


@router.get("/", response_class=HTMLResponse)
async def lpbuilder_index(
    request: Request,
    user: User = Depends(require_tool_access("lpbuilder")),
    db: AsyncSession = Depends(get_db),
):
    """LPビルダー一覧"""
    result = await db.execute(
        select(LandingPage)
        .where(LandingPage.user_id == user.id)
        .order_by(LandingPage.updated_at.desc())
    )
    pages = result.scalars().all()

    return templates.TemplateResponse(
        request, "tools/lpbuilder/index.html", {
            "user": user,
            "page": "lpbuilder",
            "pages": pages,
        }
    )


@router.post("/api/create")
async def api_create(
    user: User = Depends(require_tool_access("lpbuilder")),
    db: AsyncSession = Depends(get_db),
    title: str = Form(default=""),
    hero_title: str = Form(default=""),
    hero_subtitle: str = Form(default=""),
    hero_cta_text: str = Form(default=""),
    hero_cta_url: str = Form(default=""),
    hero_bg_color: str = Form(default="#4F46E5"),
    feature1: str = Form(default=""),
    feature2: str = Form(default=""),
    feature3: str = Form(default=""),
    about_text: str = Form(default=""),
    footer_text: str = Form(default=""),
):
    """LP作成"""
    if not title.strip():
        return {"error": "ページタイトルを入力してください。"}

    # 色バリデーション（#XXXXXX形式のみ許可）
    color = hero_bg_color.strip()
    if not re.fullmatch(r'#[0-9A-Fa-f]{6}', color):
        color = "#4F46E5"

    # URLバリデーション（javascript:等をブロック）
    cta_url = hero_cta_url.strip() or "#"
    if cta_url != "#" and not re.match(r'^https?://', cta_url):
        cta_url = "#"

    features = [f for f in [feature1, feature2, feature3] if f.strip()]

    lp = LandingPage(
        user_id=user.id,
        title=title.strip(),
        hero_title=hero_title.strip() or title.strip(),
        hero_subtitle=hero_subtitle.strip() or None,
        hero_cta_text=hero_cta_text.strip() or "お問い合わせ",
        hero_cta_url=cta_url,
        hero_bg_color=color,
        features_json=json.dumps(features, ensure_ascii=False) if features else None,
        about_text=about_text.strip() or None,
        footer_text=footer_text.strip() or None,
        is_published=True,
    )
    db.add(lp)
    await db.commit()
    return {"ok": True, "page_id": lp.page_id}


@router.post("/api/delete/{page_id}")
async def api_delete(
    page_id: str,
    user: User = Depends(require_tool_access("lpbuilder")),
    db: AsyncSession = Depends(get_db),
):
    """LP削除"""
    result = await db.execute(
        select(LandingPage).where(LandingPage.page_id == page_id, LandingPage.user_id == user.id)
    )
    lp = result.scalar_one_or_none()
    if not lp:
        return {"error": "ページが見つかりません。"}
    await db.delete(lp)
    await db.commit()
    return {"ok": True}


@router.post("/api/toggle/{page_id}")
async def api_toggle(
    page_id: str,
    user: User = Depends(require_tool_access("lpbuilder")),
    db: AsyncSession = Depends(get_db),
):
    """公開/非公開切替"""
    result = await db.execute(
        select(LandingPage).where(LandingPage.page_id == page_id, LandingPage.user_id == user.id)
    )
    lp = result.scalar_one_or_none()
    if not lp:
        return {"error": "ページが見つかりません。"}
    lp.is_published = not lp.is_published
    await db.commit()
    return {"ok": True, "is_published": lp.is_published}


# Public LP view (no auth required)
@router.get("/p/{page_id}", response_class=HTMLResponse)
async def public_lp(
    request: Request,
    page_id: str,
    db: AsyncSession = Depends(get_db),
):
    """公開LPページ"""
    result = await db.execute(
        select(LandingPage).where(LandingPage.page_id == page_id, LandingPage.is_published == True)
    )
    lp = result.scalar_one_or_none()
    if not lp:
        return HTMLResponse("<h1>ページが見つかりません</h1>", status_code=404)

    features = json.loads(lp.features_json) if lp.features_json else []

    return templates.TemplateResponse(
        request, "tools/lpbuilder/public.html", {
            "lp": lp,
            "features": features,
        }
    )
