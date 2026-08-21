"""LPビルダー - データベースモデル"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class LandingPage(Base):
    """ランディングページ"""
    __tablename__ = "landing_pages"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    page_id: Mapped[str] = mapped_column(String(36), unique=True, default=lambda: str(uuid.uuid4())[:8])
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    # JSON config for sections
    hero_title: Mapped[str | None] = mapped_column(String(255))
    hero_subtitle: Mapped[str | None] = mapped_column(Text)
    hero_cta_text: Mapped[str | None] = mapped_column(String(100))
    hero_cta_url: Mapped[str | None] = mapped_column(String(500))
    hero_bg_color: Mapped[str] = mapped_column(String(20), default="#4F46E5")
    features_json: Mapped[str | None] = mapped_column(Text)  # JSON array of features
    about_text: Mapped[str | None] = mapped_column(Text)
    footer_text: Mapped[str | None] = mapped_column(String(255))
    template: Mapped[str] = mapped_column(String(30), default="standard")
    is_published: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
