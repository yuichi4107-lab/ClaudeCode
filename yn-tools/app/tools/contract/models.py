"""契約書チェッカー - データベースモデル"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ContractHistory(Base):
    """契約書チェック履歴"""
    __tablename__ = "contract_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    check_type: Mapped[str] = mapped_column(String(30))  # risk / summary / compare / clause
    filename: Mapped[str | None] = mapped_column(String(255))
    input_chars: Mapped[int] = mapped_column(Integer, default=0)
    output_chars: Mapped[int] = mapped_column(Integer, default=0)
    result_preview: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
