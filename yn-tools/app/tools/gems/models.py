"""GEMS/GPT Library models."""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class GemsItem(Base):
    __tablename__ = "gems_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255))
    item_type: Mapped[str] = mapped_column(String(10))  # gem / gpt
    level: Mapped[str] = mapped_column(String(20))  # pro / beginner
    category: Mapped[str] = mapped_column(String(100), index=True)
    target_user: Mapped[str] = mapped_column(String(255), default="")
    use_case: Mapped[str] = mapped_column(Text, default="")
    name: Mapped[str] = mapped_column(String(255))  # Gem名 / GPT名
    description: Mapped[str] = mapped_column(Text)
    prompt_content: Mapped[str] = mapped_column(Text)
    conversation_starters: Mapped[str] = mapped_column(Text, default="")
    feature_settings: Mapped[str] = mapped_column(Text, default="")  # GPT only
    usage_guide: Mapped[str] = mapped_column(Text, default="")
    share_url: Mapped[str] = mapped_column(String(500), default="")  # Gem/GPT共有リンク
    download_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class GemsFavorite(Base):
    __tablename__ = "gems_favorites"
    __table_args__ = (
        UniqueConstraint("user_id", "item_id", name="uq_gems_fav_user_item"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    item_id: Mapped[int] = mapped_column(Integer, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
