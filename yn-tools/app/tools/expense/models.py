"""経費トラッカー - データベースモデル"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, Float, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Expense(Base):
    """経費レコード"""
    __tablename__ = "expenses"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    date: Mapped[str] = mapped_column(String(10))  # YYYY-MM-DD
    category: Mapped[str] = mapped_column(String(50))  # 交通費, 交際費, 消耗品費 etc.
    description: Mapped[str] = mapped_column(String(255))
    amount: Mapped[int] = mapped_column(Integer)  # 円
    payment_method: Mapped[str] = mapped_column(String(30), default="現金")
    receipt_text: Mapped[str | None] = mapped_column(Text)  # AI読取結果
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
