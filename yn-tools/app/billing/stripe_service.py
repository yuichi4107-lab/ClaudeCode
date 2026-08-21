"""Stripe API operations for subscription management."""

from datetime import datetime, timedelta

import stripe
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.users.models import PaymentHistory, ToolDefinition, User, UserToolSubscription

stripe.api_key = settings.stripe_secret_key


# ---------------------------------------------------------------------------
# 料金体系: 全ツールプラン (2,000円/月) + 個別ツール (各100円/月)
# ---------------------------------------------------------------------------

async def create_all_tools_checkout(
    user: User, success_url: str, cancel_url: str
) -> str:
    """全ツールプラン（2,000円/月）のCheckout Session作成"""
    params: dict = {
        "mode": "subscription",
        "line_items": [{"price": settings.stripe_price_all_tools, "quantity": 1}],
        "success_url": success_url,
        "cancel_url": cancel_url,
        "metadata": {"user_id": str(user.id), "plan_type": "all_tools"},
    }
    if user.stripe_customer_id:
        params["customer"] = user.stripe_customer_id
    else:
        params["customer_email"] = user.email

    # Freeプラン期間中 → 課金開始をFree終了翌日（有料開始日）にする
    # 例: trial_ends_at=4/24 23:59:59 → trial_end=4/25 00:00:00
    if user.is_in_trial and user.trial_ends_at:
        paid_start = (user.trial_ends_at + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0,
        )
        params["subscription_data"] = {
            "trial_end": int(paid_start.timestamp()),
        }

    session = stripe.checkout.Session.create(**params)
    return session.url


async def create_tool_checkout(
    user: User,
    tool_slugs: list[str],
    db: AsyncSession,
    success_url: str,
    cancel_url: str,
) -> str:
    """個別ツール購入用のCheckout Session作成"""
    result = await db.execute(
        select(ToolDefinition).where(
            ToolDefinition.slug.in_(tool_slugs),
            ToolDefinition.is_active == True,
        )
    )
    tools = result.scalars().all()
    if not tools:
        raise ValueError("No valid tools selected")

    line_items = [{"price": t.stripe_price_id, "quantity": 1} for t in tools]

    params: dict = {
        "mode": "subscription",
        "line_items": line_items,
        "success_url": success_url,
        "cancel_url": cancel_url,
        "metadata": {
            "user_id": str(user.id),
            "plan_type": "per_tool",
            "tool_slugs": ",".join(t.slug for t in tools),
        },
    }
    if user.stripe_customer_id:
        params["customer"] = user.stripe_customer_id
    else:
        params["customer_email"] = user.email

    # Freeプラン期間中 → 課金開始をFree終了翌日（有料開始日）にする
    # 例: trial_ends_at=4/24 23:59:59 → trial_end=4/25 00:00:00
    if user.is_in_trial and user.trial_ends_at:
        paid_start = (user.trial_ends_at + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0,
        )
        params["subscription_data"] = {
            "trial_end": int(paid_start.timestamp()),
        }

    session = stripe.checkout.Session.create(**params)
    return session.url


# ---------------------------------------------------------------------------
# Webhook handlers
# ---------------------------------------------------------------------------

async def handle_checkout_completed(session_data: dict, db: AsyncSession):
    """Handle checkout.session.completed webhook - activate subscription."""
    metadata = session_data.get("metadata", {})
    user_id = metadata.get("user_id")
    if not user_id:
        return

    result = await db.execute(select(User).where(User.id == int(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        return

    plan_type = metadata.get("plan_type", "pro")
    user.stripe_customer_id = session_data.get("customer")
    user.stripe_subscription_id = session_data.get("subscription")

    if plan_type == "all_tools":
        user.plan = "all_tools"
        # 全ツールプランの場合、個別購読レコードは不要
    elif plan_type == "per_tool":
        user.plan = "per_tool"
        tool_slugs = metadata.get("tool_slugs", "").split(",")
        for slug in tool_slugs:
            if not slug:
                continue
            existing = await db.execute(
                select(UserToolSubscription).where(
                    UserToolSubscription.user_id == user.id,
                    UserToolSubscription.tool_slug == slug,
                )
            )
            sub = existing.scalar_one_or_none()
            if sub:
                sub.is_active = True
                sub.canceled_at = None
            else:
                db.add(UserToolSubscription(
                    user_id=user.id,
                    tool_slug=slug,
                    is_active=True,
                ))
    else:
        # Legacy pro plan
        user.plan = "pro"

    await db.commit()


async def handle_invoice_paid(invoice_data: dict, db: AsyncSession):
    """Handle invoice.paid webhook - record payment + apply pending downgrade."""
    customer_id = invoice_data.get("customer")
    if not customer_id:
        return

    result = await db.execute(
        select(User).where(User.stripe_customer_id == customer_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        return

    # 支払い記録
    payment = PaymentHistory(
        user_id=user.id,
        stripe_payment_intent_id=invoice_data.get("payment_intent"),
        amount=invoice_data.get("amount_paid", 0),
        currency=invoice_data.get("currency", "jpy"),
        status="succeeded",
        paid_at=datetime.utcnow(),
    )
    db.add(payment)

    # 保留中のプラン変更を適用
    sub_id = invoice_data.get("subscription")
    if sub_id and user.stripe_subscription_id == sub_id:
        sub = stripe.Subscription.retrieve(sub_id)

        # (1) all_tools → per_tool ダウングレードの適用
        pending_plan = sub.metadata.get("pending_plan")
        if pending_plan:
            pending_slugs = [
                s for s in sub.metadata.get("pending_tool_slugs", "").split(",") if s
            ]
            new_items = await _build_subscription_items(sub, pending_plan, pending_slugs, db)
            stripe.Subscription.modify(
                sub_id,
                items=new_items,
                proration_behavior="none",
                metadata={"pending_plan": "", "pending_tool_slugs": ""},
            )
            user.plan = pending_plan
            # 全ツール無効化 → 新しいツールのみ有効化
            await db.execute(
                update(UserToolSubscription)
                .where(UserToolSubscription.user_id == user.id)
                .values(is_active=False, canceled_at=datetime.utcnow())
            )
            for slug in pending_slugs:
                existing = await db.execute(
                    select(UserToolSubscription).where(
                        UserToolSubscription.user_id == user.id,
                        UserToolSubscription.tool_slug == slug,
                    )
                )
                rec = existing.scalar_one_or_none()
                if rec:
                    rec.is_active = True
                    rec.canceled_at = None
                else:
                    db.add(UserToolSubscription(
                        user_id=user.id, tool_slug=slug, is_active=True,
                    ))

        # (2) 削除予約されたツールのDB無効化（期間終了）
        pending_removal = sub.metadata.get("pending_removal_slugs")
        if pending_removal:
            removal_slugs = [s for s in pending_removal.split(",") if s]
            for slug in removal_slugs:
                existing = await db.execute(
                    select(UserToolSubscription).where(
                        UserToolSubscription.user_id == user.id,
                        UserToolSubscription.tool_slug == slug,
                    )
                )
                rec = existing.scalar_one_or_none()
                if rec:
                    rec.is_active = False
                    rec.canceled_at = datetime.utcnow()
            stripe.Subscription.modify(
                sub_id,
                metadata={"pending_removal_slugs": "", "pending_removal_date": ""},
            )

    await db.commit()


async def handle_subscription_deleted(sub_data: dict, db: AsyncSession):
    """Handle customer.subscription.deleted webhook - downgrade to free."""
    customer_id = sub_data.get("customer")
    if not customer_id:
        return

    result = await db.execute(
        select(User).where(User.stripe_customer_id == customer_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        return

    user.plan = "free"
    user.stripe_subscription_id = None

    # 個別ツール購読も全て無効化
    await db.execute(
        update(UserToolSubscription)
        .where(UserToolSubscription.user_id == user.id)
        .values(is_active=False, canceled_at=datetime.utcnow())
    )

    await db.commit()


# ---------------------------------------------------------------------------
# Plan change (upgrade / downgrade)
# ---------------------------------------------------------------------------
#
# ルール:
#   - Freeプラン期間中の新規契約 → 課金開始はFree終了日から（Stripe trial_end）
#   - 追加ツール → 即時反映 + 追加分の月額を請求（日割りなし）
#     ※ 追加ツールの有効期間は既存サブスクリプションのperiod_endに揃う
#   - 削除ツール → 次の更新日まで使用可能、更新時にStripe/DBから削除
#   - 追加+削除が同時 → 追加分は即時請求、削除分は次の更新で反映
#   - per_tool → all_tools: アップグレード（即時 + 差額請求）
#   - all_tools → per_tool: ダウングレード（次の更新から）
# ---------------------------------------------------------------------------

async def get_monthly_cost(plan: str, tool_slugs: list[str], db: AsyncSession) -> int:
    """プラン構成から月額コストを計算"""
    if plan == "all_tools":
        return 2000
    if plan == "pro":
        return 500
    if plan == "per_tool" and tool_slugs:
        result = await db.execute(
            select(ToolDefinition).where(
                ToolDefinition.slug.in_(tool_slugs),
                ToolDefinition.is_active == True,
            )
        )
        return sum(t.monthly_price for t in result.scalars().all())
    return 0


async def _get_tool_price_map(slugs: list[str], db: AsyncSession) -> dict[str, dict]:
    """ツールslug → {monthly_price, stripe_price_id} のマッピングを返す"""
    if not slugs:
        return {}
    result = await db.execute(
        select(ToolDefinition).where(
            ToolDefinition.slug.in_(slugs),
            ToolDefinition.is_active == True,
        )
    )
    return {
        t.slug: {"price": t.monthly_price, "stripe_price_id": t.stripe_price_id}
        for t in result.scalars().all()
    }


async def _build_subscription_items(
    sub, target_plan: str, target_tool_slugs: list[str], db: AsyncSession
) -> list[dict]:
    """Stripeサブスクリプションの新しいitems一覧を構築（全置換）"""
    items: list[dict] = [{"id": item["id"], "deleted": True} for item in sub["items"]["data"]]

    if target_plan == "all_tools":
        items.append({"price": settings.stripe_price_all_tools})
    elif target_plan == "per_tool":
        tool_map = await _get_tool_price_map(target_tool_slugs, db)
        for slug in target_tool_slugs:
            info = tool_map.get(slug)
            if info and info["stripe_price_id"]:
                items.append({"price": info["stripe_price_id"]})
    return items


def _get_stripe_price_to_item_map(sub) -> dict[str, str]:
    """Stripeサブスクリプションの price_id → item_id マッピング"""
    return {item["price"]["id"]: item["id"] for item in sub["items"]["data"]}


async def _get_current_tool_slugs(user: User, db: AsyncSession) -> list[str]:
    """ユーザーの現在有効なツールslug一覧"""
    result = await db.execute(
        select(UserToolSubscription.tool_slug).where(
            UserToolSubscription.user_id == user.id,
            UserToolSubscription.is_active == True,
        )
    )
    return [row[0] for row in result.all()]


async def change_plan(
    user: User,
    target_plan: str,
    target_tool_slugs: list[str],
    db: AsyncSession,
) -> dict:
    """
    プラン変更処理。

    - 追加ツール: 即時反映 + 追加分の金額を請求（日割りなし）
    - 削除ツール: 次の更新日まで使用可能、更新時に削除
    - per_tool → all_tools: アップグレード（即時 + 差額請求）
    - all_tools → per_tool: ダウングレード（次の更新から）
    """
    if not user.stripe_subscription_id:
        raise ValueError("no_active_subscription")

    sub = stripe.Subscription.retrieve(user.stripe_subscription_id)
    period_end = datetime.fromtimestamp(sub["current_period_end"])
    # 表示用: Stripeの period_end（翌月同日）から-1日で「前日まで」表記
    period_end_display = period_end - timedelta(days=1)

    # ======================================================================
    # per_tool → all_tools（常にアップグレード）
    # ======================================================================
    if target_plan == "all_tools" and user.plan != "all_tools":
        current_slugs = await _get_current_tool_slugs(user, db)
        current_cost = await get_monthly_cost(user.plan, current_slugs, db)
        difference = 2000 - current_cost

        new_items = await _build_subscription_items(sub, "all_tools", [], db)
        stripe.Subscription.modify(
            user.stripe_subscription_id,
            items=new_items,
            proration_behavior="none",
        )

        # 差額を即時請求
        if difference > 0:
            stripe.InvoiceItem.create(
                customer=user.stripe_customer_id,
                amount=difference,
                currency="jpy",
                description=f"全ツールプランへのアップグレード差額（{current_cost:,}円 → 2,000円）",
            )
            inv = stripe.Invoice.create(
                customer=user.stripe_customer_id, auto_advance=True,
            )
            stripe.Invoice.pay(inv.id)

        user.plan = "all_tools"
        # 個別ツール購読を全て無効化
        await db.execute(
            update(UserToolSubscription)
            .where(UserToolSubscription.user_id == user.id)
            .values(is_active=False, canceled_at=datetime.utcnow())
        )
        await db.commit()

        return {
            "type": "upgrade",
            "old_cost": current_cost,
            "new_cost": 2000,
            "charged": max(difference, 0),
        }

    # ======================================================================
    # all_tools → per_tool（常にダウングレード → 次の更新から）
    # ======================================================================
    if target_plan == "per_tool" and user.plan in ("all_tools", "pro"):
        current_cost = await get_monthly_cost(user.plan, [], db)
        new_cost = await get_monthly_cost("per_tool", target_tool_slugs, db)

        stripe.Subscription.modify(
            user.stripe_subscription_id,
            metadata={
                "pending_plan": "per_tool",
                "pending_tool_slugs": ",".join(target_tool_slugs),
            },
        )

        return {
            "type": "downgrade",
            "old_cost": current_cost,
            "new_cost": new_cost,
            "effective_date": period_end.strftime("%Y年%m月%d日"),
        }

    # ======================================================================
    # per_tool → per_tool（ツール追加/削除）
    # ======================================================================
    if target_plan == "per_tool" and user.plan == "per_tool":
        current_slugs = set(await _get_current_tool_slugs(user, db))
        new_slugs = set(target_tool_slugs)

        added = new_slugs - current_slugs
        removed = current_slugs - new_slugs

        if not added and not removed:
            raise ValueError("no_change")

        # --- 追加ツール: Stripeに追加 + 追加分を即時請求 ---
        added_cost = 0
        if added:
            tool_map = await _get_tool_price_map(list(added), db)
            for slug in added:
                info = tool_map.get(slug)
                if info and info["stripe_price_id"]:
                    stripe.SubscriptionItem.create(
                        subscription=user.stripe_subscription_id,
                        price=info["stripe_price_id"],
                        proration_behavior="none",
                    )
                    added_cost += info["price"]

            # 追加分を即時請求
            if added_cost > 0:
                stripe.InvoiceItem.create(
                    customer=user.stripe_customer_id,
                    amount=added_cost,
                    currency="jpy",
                    description=f"ツール追加（{len(added)}個 / {added_cost:,}円）",
                )
                inv = stripe.Invoice.create(
                    customer=user.stripe_customer_id, auto_advance=True,
                )
                stripe.Invoice.pay(inv.id)

            # DB: 追加ツールを有効化
            for slug in added:
                existing = await db.execute(
                    select(UserToolSubscription).where(
                        UserToolSubscription.user_id == user.id,
                        UserToolSubscription.tool_slug == slug,
                    )
                )
                rec = existing.scalar_one_or_none()
                if rec:
                    rec.is_active = True
                    rec.canceled_at = None
                else:
                    db.add(UserToolSubscription(
                        user_id=user.id, tool_slug=slug, is_active=True,
                    ))

        # --- 削除ツール: Stripeから即時削除（次回請求に含めない） ---
        #     DB上は canceled_at=期間終了日 で使用可能を維持
        if removed:
            price_to_item = _get_stripe_price_to_item_map(sub)
            tool_map = await _get_tool_price_map(list(removed), db)
            pending_remove_slugs = []

            for slug in removed:
                info = tool_map.get(slug)
                if info and info["stripe_price_id"]:
                    item_id = price_to_item.get(info["stripe_price_id"])
                    if item_id:
                        stripe.SubscriptionItem.delete(
                            item_id, proration_behavior="none",
                        )

                # DB: 削除予約（期間終了まで使用可能）
                existing = await db.execute(
                    select(UserToolSubscription).where(
                        UserToolSubscription.user_id == user.id,
                        UserToolSubscription.tool_slug == slug,
                    )
                )
                rec = existing.scalar_one_or_none()
                if rec:
                    rec.is_active = False
                    rec.canceled_at = period_end
                pending_remove_slugs.append(slug)

            # メタデータに削除予約を記録
            stripe.Subscription.modify(
                user.stripe_subscription_id,
                metadata={
                    "pending_removal_slugs": ",".join(pending_remove_slugs),
                    "pending_removal_date": period_end.strftime("%Y-%m-%d"),
                },
            )

        await db.commit()

        return {
            "type": "mixed" if (added and removed) else ("add" if added else "remove"),
            "added": list(added),
            "removed": list(removed),
            "charged": added_cost,
            "removal_date": period_end_display.strftime("%Y年%m月%d日") if removed else None,
        }

    raise ValueError("invalid_plan_change")


async def cancel_pending_downgrade(user: User) -> bool:
    """保留中のダウングレードをキャンセル"""
    if not user.stripe_subscription_id:
        return False
    sub = stripe.Subscription.retrieve(user.stripe_subscription_id)
    if sub.metadata.get("pending_plan"):
        stripe.Subscription.modify(
            user.stripe_subscription_id,
            metadata={"pending_plan": "", "pending_tool_slugs": ""},
        )
        return True
    return False


def cancel_subscription(subscription_id: str) -> None:
    """Cancel a Stripe subscription at period end."""
    stripe.Subscription.modify(
        subscription_id,
        cancel_at_period_end=True,
    )


def create_billing_portal_session(customer_id: str, return_url: str) -> str:
    """Create a Stripe Billing Portal session for managing subscription."""
    session = stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=return_url,
    )
    return session.url
