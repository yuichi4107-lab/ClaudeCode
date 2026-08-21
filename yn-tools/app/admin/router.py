"""管理者ダッシュボード用 FastAPI ルーター"""

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from app.core.templates import make_templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_admin
from app.database import get_db
from app.users.models import PaymentHistory, User, UserToolSubscription

router = APIRouter(prefix="/admin", tags=["admin"])

templates = make_templates("app/templates")


@router.get("/", response_class=HTMLResponse)
async def admin_index(
    request: Request,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """管理者ダッシュボードトップ: ユーザー統計サマリー"""
    total_users = (await db.execute(select(func.count(User.id)))).scalar()
    free_users = (
        await db.execute(select(func.count(User.id)).where(User.plan == "free"))
    ).scalar()
    pro_users = (
        await db.execute(
            select(func.count(User.id)).where(
                User.plan.in_(["pro", "all_tools", "per_tool"])
            )
        )
    ).scalar()
    admin_users = (
        await db.execute(
            select(func.count(User.id)).where(User.is_admin == True)  # noqa: E712
        )
    ).scalar()
    active_users = (
        await db.execute(
            select(func.count(User.id)).where(User.is_active == True)  # noqa: E712
        )
    ).scalar()
    return templates.TemplateResponse(
        request,
        "admin/index.html",
        {
            "user": user,
            "total_users": total_users,
            "free_users": free_users,
            "pro_users": pro_users,
            "admin_users": admin_users,
            "active_users": active_users,
        },
    )


@router.get("/users", response_class=HTMLResponse)
async def admin_users(
    request: Request,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """ユーザー一覧（最大1000件）"""
    result = await db.execute(
        select(User).order_by(User.created_at.desc()).limit(1000)
    )
    users = result.scalars().all()
    return templates.TemplateResponse(
        request,
        "admin/users.html",
        {"user": user, "users": users},
    )


@router.get("/users/{user_id}", response_class=HTMLResponse)
async def admin_user_detail(
    user_id: int,
    request: Request,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """ユーザー詳細・編集フォーム"""
    result = await db.execute(select(User).where(User.id == user_id))
    target_user = result.scalar_one_or_none()
    if not target_user:
        raise HTTPException(status_code=404, detail="ユーザーが見つかりません")

    # 個別ツール購読一覧
    sub_result = await db.execute(
        select(UserToolSubscription).where(
            UserToolSubscription.user_id == user_id
        )
    )
    subscriptions = sub_result.scalars().all()

    return templates.TemplateResponse(
        request,
        "admin/user_detail.html",
        {
            "user": user,
            "target_user": target_user,
            "subscriptions": subscriptions,
        },
    )


@router.post("/users/{user_id}/update")
async def admin_user_update(
    user_id: int,
    request: Request,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    plan: str = Form(...),
    is_admin: str = Form(default="off"),
    is_active: str = Form(default="off"),
):
    """ユーザー属性更新（plan / is_admin / is_active）"""
    result = await db.execute(select(User).where(User.id == user_id))
    target_user = result.scalar_one_or_none()
    if not target_user:
        raise HTTPException(status_code=404, detail="ユーザーが見つかりません")

    valid_plans = ("free", "per_tool", "all_tools", "pro")
    if plan not in valid_plans:
        raise HTTPException(status_code=400, detail=f"無効なプラン: {plan}")

    target_user.plan = plan
    target_user.is_admin = is_admin == "on"
    target_user.is_active = is_active == "on"

    await db.commit()
    return RedirectResponse(url=f"/admin/users/{user_id}", status_code=303)


@router.post("/users/{user_id}/logout")
async def admin_user_force_logout(
    user_id: int,
    request: Request,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """強制ログアウト: is_active=False を設定し次回リクエスト時にアクセス不可にする"""
    result = await db.execute(select(User).where(User.id == user_id))
    target_user = result.scalar_one_or_none()
    if not target_user:
        raise HTTPException(status_code=404, detail="ユーザーが見つかりません")

    target_user.is_active = False
    await db.commit()
    return RedirectResponse(url=f"/admin/users/{user_id}", status_code=303)


@router.get("/billing", response_class=HTMLResponse)
async def admin_billing(
    request: Request,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """課金履歴サマリー（status='succeeded' のみ集計）"""
    from sqlalchemy import case, extract

    # プラン別ユーザー数
    plan_counts_result = await db.execute(
        select(User.plan, func.count(User.id))
        .group_by(User.plan)
        .order_by(User.plan)
    )
    plan_counts = {row[0]: row[1] for row in plan_counts_result.all()}

    # Stripe customer 紐付け状況
    stripe_linked = (
        await db.execute(
            select(func.count(User.id)).where(User.stripe_customer_id != None)  # noqa: E711
        )
    ).scalar()
    stripe_unlinked = (
        await db.execute(
            select(func.count(User.id)).where(User.stripe_customer_id == None)  # noqa: E711
        )
    ).scalar()

    # per_tool 購読合計件数（is_active=True のみ）
    per_tool_subs = (
        await db.execute(
            select(func.count(UserToolSubscription.id)).where(
                UserToolSubscription.is_active == True  # noqa: E712
            )
        )
    ).scalar()

    # 月次売上サマリー（succeeded のみ）
    monthly_result = await db.execute(
        select(
            extract("year", PaymentHistory.paid_at).label("year"),
            extract("month", PaymentHistory.paid_at).label("month"),
            func.sum(PaymentHistory.amount).label("total"),
            func.count(
                case((PaymentHistory.tool_slug == None, 1))  # noqa: E711
            ).label("subscription_count"),
            func.count(
                case((PaymentHistory.tool_slug != None, 1))  # noqa: E711
            ).label("tool_count"),
        )
        .where(PaymentHistory.status == "succeeded")
        .group_by("year", "month")
        .order_by("year", "month")
    )
    monthly_summary = monthly_result.all()

    # 合計売上
    total_revenue = (
        await db.execute(
            select(func.sum(PaymentHistory.amount)).where(
                PaymentHistory.status == "succeeded"
            )
        )
    ).scalar() or 0

    return templates.TemplateResponse(
        request,
        "admin/billing.html",
        {
            "user": user,
            "plan_counts": plan_counts,
            "stripe_linked": stripe_linked,
            "stripe_unlinked": stripe_unlinked,
            "per_tool_subs": per_tool_subs,
            "monthly_summary": monthly_summary,
            "total_revenue": total_revenue,
        },
    )
