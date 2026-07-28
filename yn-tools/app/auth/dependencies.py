"""Auth dependencies for FastAPI route injection."""

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.demo import GUEST_USER
from app.database import get_db
from app.users.models import User, UserToolSubscription


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """Get current logged-in user from session cookie. Returns None if not logged in."""
    if settings.demo_mode:
        return GUEST_USER  # type: ignore[return-value]
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user and not user.is_active:
        return None
    return user


async def require_login(
    user: User | None = Depends(get_current_user),
) -> User:
    """Require authenticated user. Raises 401 if not logged in."""
    if settings.demo_mode:
        return GUEST_USER  # type: ignore[return-value]
    if not user:
        raise HTTPException(status_code=401, detail="login_required")
    return user


async def require_active_plan(
    user: User = Depends(require_login),
) -> User:
    """Require user with active plan (pro or within trial). Raises 402 if expired."""
    if settings.demo_mode:
        return GUEST_USER  # type: ignore[return-value]
    if user.has_active_plan:
        return user
    raise HTTPException(status_code=402, detail="plan_expired")


def require_tool_access(tool_slug: str):
    """Factory that returns a dependency checking access to a specific tool."""

    async def _check(
        request: Request,
        user: User = Depends(require_login),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        if settings.demo_mode:
            return GUEST_USER  # type: ignore[return-value]
        if user.has_full_access:
            return user
        if user.plan == "per_tool":
            result = await db.execute(
                select(UserToolSubscription).where(
                    UserToolSubscription.user_id == user.id,
                    UserToolSubscription.tool_slug == tool_slug,
                    UserToolSubscription.is_active == True,
                )
            )
            if result.scalar_one_or_none():
                return user
        raise HTTPException(status_code=402, detail="tool_not_subscribed")

    return _check


async def require_admin(
    user: User = Depends(require_login),
) -> User:
    """Require admin user. Raises 403 if not admin."""
    if settings.demo_mode:
        # 管理者機能はデモでは閉じる
        raise HTTPException(status_code=404, detail="not_found")
    if user.is_admin:
        return user
    raise HTTPException(status_code=403, detail="admin_required")
