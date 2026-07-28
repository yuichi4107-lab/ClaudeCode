"""売上ダッシュボード - データベースモデル"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SalesRecord(Base):
    """売上レコード"""
    __tablename__ = "sales_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    date: Mapped[str] = mapped_column(String(10))  # YYYY-MM-DD
    client_name: Mapped[str] = mapped_column(String(255))
    item_name: Mapped[str] = mapped_column(String(255))
    amount: Mapped[int] = mapped_column(Integer)  # 円
    category: Mapped[str] = mapped_column(String(50), default="その他")
    memo: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class SalesGoal(Base):
    """月次売上目標"""
    __tablename__ = "sales_goals"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    year: Mapped[int] = mapped_column(Integer)
    month: Mapped[int] = mapped_column(Integer)
    target_amount: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
