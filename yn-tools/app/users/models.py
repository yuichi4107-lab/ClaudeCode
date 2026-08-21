from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    google_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    avatar_url: Mapped[str | None] = mapped_column(String(500))
    plan: Mapped[str] = mapped_column(String(20), default="free")  # free / per_tool / all_tools / pro(legacy)
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime)
    stripe_customer_id: Mapped[str | None] = mapped_column(String(255))
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    @property
    def has_active_plan(self) -> bool:
        if self.is_admin:
            return True
        if self.plan in ("pro", "all_tools", "per_tool"):
            return True
        if self.trial_ends_at and self.trial_ends_at > datetime.utcnow():
            return True
        return False

    @property
    def has_full_access(self) -> bool:
        """全ツールにアクセス可能か（管理者/全ツールプラン/旧Pro/トライアル中）"""
        if self.is_admin:
            return True
        if self.plan in ("pro", "all_tools"):
            return True
        if self.trial_ends_at and self.trial_ends_at > datetime.utcnow():
            return True
        return False

    @property
    def is_in_trial(self) -> bool:
        """トライアル期間中かどうか"""
        if self.trial_ends_at and self.trial_ends_at > datetime.utcnow():
            return True
        return False

    @property
    def has_paid_plan_during_trial(self) -> bool:
        """トライアル中に有料プランを契約済みか"""
        return self.is_in_trial and self.plan in ("per_tool", "all_tools", "pro")

    @property
    def trial_remaining_days(self) -> int | None:
        if self.plan == "pro":
            return None
        if not self.trial_ends_at:
            return 0
        delta = self.trial_ends_at - datetime.utcnow()
        return max(0, delta.days)

    def __repr__(self) -> str:
        return f"<User(id={self.id}, email={self.email!r}, plan={self.plan!r})>"


class PaymentHistory(Base):
    __tablename__ = "payment_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    stripe_payment_intent_id: Mapped[str | None] = mapped_column(String(255))
    amount: Mapped[int] = mapped_column(Integer)  # JPY
    currency: Mapped[str] = mapped_column(String(10), default="jpy")
    status: Mapped[str] = mapped_column(String(50))  # succeeded / failed / refunded
    tool_slug: Mapped[str | None] = mapped_column(String(50))  # null = 全ツールプラン
    paid_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ToolDefinition(Base):
    __tablename__ = "tool_definitions"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, server_default="")
    monthly_price: Mapped[int] = mapped_column(Integer, server_default="100")  # JPY
    stripe_product_id: Mapped[str | None] = mapped_column(String(255))
    stripe_price_id: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    display_order: Mapped[int] = mapped_column(Integer, server_default="0")
    icon_emoji: Mapped[str] = mapped_column(String(10), server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    def __repr__(self) -> str:
        return f"<ToolDefinition(slug={self.slug!r}, name={self.name!r})>"


class UserToolSubscription(Base):
    __tablename__ = "user_tool_subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), index=True)
    tool_slug: Mapped[str] = mapped_column(String(50), index=True)
    stripe_subscription_item_id: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    subscribed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime)

    __table_args__ = (
        UniqueConstraint("user_id", "tool_slug", name="uq_user_tool"),
    )

    def __repr__(self) -> str:
        return f"<UserToolSubscription(user_id={self.user_id}, tool={self.tool_slug!r}, active={self.is_active})>"
