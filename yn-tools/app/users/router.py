"""User account routes."""

from datetime import datetime, timedelta

import stripe
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from app.core.templates import make_templates
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_login
from app.billing.stripe_service import cancel_subscription, get_monthly_cost
from app.config import settings
from app.database import get_db
from app.users.models import ToolDefinition, User, UserToolSubscription

router = APIRouter(prefix="/account", tags=["account"])
templates = make_templates("app/templates")

stripe.api_key = settings.stripe_secret_key


def _get_subscription_info(subscription_id: str) -> dict | None:
    """Stripeからサブスクリプション情報を取得

    有効期間の表示ルール:
      開始日〜翌月同日の前日（例: 4/25開始 → 4/25〜5/24）
      Stripeの current_period_end は翌月同日を返すので -1日 で表示
    """
    if not subscription_id:
        return None
    try:
        sub = stripe.Subscription.retrieve(subscription_id)
        period_start = datetime.fromtimestamp(sub.current_period_start)
        # Stripeの period_end（翌月同日）から1日引いて「前日まで」表記にする
        period_end_display = datetime.fromtimestamp(sub.current_period_end) - timedelta(days=1)
        return {
            "current_period_start": period_start.strftime("%Y年%m月%d日"),
            "current_period_end": period_end_display.strftime("%Y年%m月%d日"),
            "cancel_at_period_end": sub.cancel_at_period_end,
            "status": sub.status,
        }
    except Exception:
        return None


@router.get("", response_class=HTMLResponse)
async def account_page(
    request: Request,
    user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db),
):
    """Show account/profile page with plan info."""
    # 利用中ツール一覧（is_active=True + 削除予約中で期間内のもの）
    subscribed_tools: list[str] = []
    if user.plan == "per_tool":
        result = await db.execute(
            select(UserToolSubscription.tool_slug).where(
                UserToolSubscription.user_id == user.id,
                or_(
                    UserToolSubscription.is_active == True,
                    and_(
                        UserToolSubscription.canceled_at != None,
                        UserToolSubscription.canceled_at > datetime.utcnow(),
                    ),
                ),
            )
        )
        subscribed_tools = [row[0] for row in result.all()]

    # ツールマスタ（名前表示用）
    result = await db.execute(
        select(ToolDefinition).where(ToolDefinition.is_active == True)
        .order_by(ToolDefinition.display_order)
    )
    tools = result.scalars().all()
    tool_names = {t.slug: t.name for t in tools}

    # Stripeサブスクリプション情報
    subscription_info = _get_subscription_info(user.stripe_subscription_id)

    # 保留中のダウングレード確認
    pending_downgrade = None
    if user.stripe_subscription_id:
        try:
            sub = stripe.Subscription.retrieve(user.stripe_subscription_id)
            pending_plan = sub.metadata.get("pending_plan")
            if pending_plan:
                pending_slugs = [s for s in sub.metadata.get("pending_tool_slugs", "").split(",") if s]
                pending_cost = await get_monthly_cost(pending_plan, pending_slugs, db)
                pending_downgrade = {"plan": pending_plan, "new_cost": pending_cost}
        except Exception:
            pass

    # Free期間中の有料開始日（trial_ends_atの翌日）
    paid_start_date = None
    if user.is_in_trial and user.trial_ends_at:
        paid_start = (user.trial_ends_at + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0,
        )
        paid_start_date = paid_start.strftime("%Y年%m月%d日")

    return templates.TemplateResponse(
        request, "account/profile.html", {
            "user": user,
            "subscribed_tools": subscribed_tools,
            "tool_names": tool_names,
            "subscription_info": subscription_info,
            "pending_downgrade": pending_downgrade,
            "paid_start_date": paid_start_date,
        }
    )


@router.get("/plan", response_class=HTMLResponse)
async def plan_page(
    request: Request,
    user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db),
):
    """Show plan change page."""
    # 現在有効なツール（is_active=True のみ。削除予約中は含めない＝チェック外す）
    subscribed_slugs: set[str] = set()
    if user.plan == "per_tool":
        result = await db.execute(
            select(UserToolSubscription.tool_slug).where(
                UserToolSubscription.user_id == user.id,
                UserToolSubscription.is_active == True,
            )
        )
        subscribed_slugs = {row[0] for row in result.all()}

    result = await db.execute(
        select(ToolDefinition).where(ToolDefinition.is_active == True)
        .order_by(ToolDefinition.display_order)
    )
    tools = result.scalars().all()

    # 現在の月額コスト
    current_cost = await get_monthly_cost(user.plan, list(subscribed_slugs), db)

    # 保留中のダウングレード確認
    pending_downgrade = None
    if user.stripe_subscription_id:
        sub_info = _get_subscription_info(user.stripe_subscription_id)
        if sub_info:
            sub = stripe.Subscription.retrieve(user.stripe_subscription_id)
            pending_plan = sub.metadata.get("pending_plan")
            if pending_plan:
                pending_slugs = [s for s in sub.metadata.get("pending_tool_slugs", "").split(",") if s]
                pending_cost = await get_monthly_cost(pending_plan, pending_slugs, db)
                pending_downgrade = {"plan": pending_plan, "new_cost": pending_cost}

    return templates.TemplateResponse(
        request, "account/plan.html", {
            "user": user,
            "tools": tools,
            "subscribed_slugs": subscribed_slugs,
            "current_cost": current_cost,
            "pending_downgrade": pending_downgrade,
        }
    )


@router.get("/cancel", response_class=HTMLResponse)
async def cancel_page(request: Request, user: User = Depends(require_login)):
    """Show subscription cancellation confirmation page."""
    if not user.stripe_subscription_id:
        return RedirectResponse(url="/account", status_code=303)
    return templates.TemplateResponse(
        request, "account/cancel.html", {"user": user}
    )


@router.post("/cancel")
async def cancel_action(
    request: Request,
    user: User = Depends(require_login),
    reason: str = Form(""),
):
    """Cancel subscription via Stripe."""
    if not user.stripe_subscription_id:
        return RedirectResponse(url="/account", status_code=303)

    cancel_subscription(user.stripe_subscription_id)

    return templates.TemplateResponse(
        request, "account/cancel_done.html", {"user": user, "reason": reason}
    )
