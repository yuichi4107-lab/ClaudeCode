"""Auth routes: Google OAuth login/logout."""

import calendar
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from app.core.templates import make_templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.google_oauth import oauth
from app.config import settings
from app.database import get_db
from app.users.models import User

router = APIRouter(prefix="/auth", tags=["auth"])
templates = make_templates("app/templates")


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Show login page with Google sign-in button."""
    user_id = request.session.get("user_id")
    if user_id:
        return RedirectResponse(url="/dashboard", status_code=303)
    return templates.TemplateResponse(request, "auth/login.html", {})


@router.get("/google")
async def google_login(request: Request):
    """Redirect to Google OAuth consent screen."""
    redirect_uri = settings.google_redirect_uri
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/callback")
async def google_callback(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Handle Google OAuth callback."""
    token = await oauth.google.authorize_access_token(request)
    userinfo = token.get("userinfo")
    if not userinfo:
        return RedirectResponse(url="/auth/login?error=auth_failed", status_code=303)

    google_id = userinfo["sub"]
    email = userinfo["email"]
    name = userinfo.get("name", email)
    avatar_url = userinfo.get("picture")

    # Find or create user
    result = await db.execute(select(User).where(User.google_id == google_id))
    user = result.scalar_one_or_none()

    if user:
        # Update profile info from Google
        user.name = name
        user.avatar_url = avatar_url
    else:
        # New user - create with trial period
        # Freeプラン: 登録日から翌月同日の前日まで
        # 例: 3/25登録 → 4/24 23:59:59 まで（4/25から有料開始）
        now = datetime.utcnow()
        next_month = now.month + 1
        next_year = now.year
        if next_month > 12:
            next_month = 1
            next_year += 1
        # 翌月の同日が存在しない場合は翌月末日を使用（例: 1/31 → 2/28）
        max_day = calendar.monthrange(next_year, next_month)[1]
        same_day_next_month = min(now.day, max_day)
        trial_end = now.replace(
            year=next_year, month=next_month, day=same_day_next_month,
            hour=0, minute=0, second=0, microsecond=0,
        ) - timedelta(seconds=1)  # 翌月同日の前日 23:59:59

        user = User(
            google_id=google_id,
            email=email,
            name=name,
            avatar_url=avatar_url,
            plan="free",
            trial_ends_at=trial_end,
        )
        db.add(user)

    await db.commit()
    await db.refresh(user)

    # Set session
    request.session["user_id"] = user.id

    return RedirectResponse(url="/dashboard", status_code=303)


@router.get("/logout")
async def logout(request: Request):
    """Clear session and redirect to top page."""
    request.session.clear()
    return RedirectResponse(url="/", status_code=303)
