"""ステップメール作成ツール - データベースモデル"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class StepMailSeries(Base):
    """ステップメールシリーズ（シリーズ単位の管理）"""
    __tablename__ = "stepmail_series"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    title: Mapped[str] = mapped_column(String(200))
    business_purpose: Mapped[str] = mapped_column(String(30))
    product_name: Mapped[str] = mapped_column(String(200))
    target_audience: Mapped[str] = mapped_column(String(300))
    step_count: Mapped[int] = mapped_column(Integer)
    tone: Mapped[str] = mapped_column(String(20))
    cta_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    seller_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    extra_info: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft/generated
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class StepMailItem(Base):
    """ステップメール各通（通ごとの内容）"""
    __tablename__ = "stepmail_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    series_id: Mapped[int] = mapped_column(Integer, index=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    step_number: Mapped[int] = mapped_column(Integer)
    subject: Mapped[str] = mapped_column(String(300))
    preheader: Mapped[str | None] = mapped_column(String(100), nullable=True)
    body: Mapped[str] = mapped_column(Text)
    cta_text: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
