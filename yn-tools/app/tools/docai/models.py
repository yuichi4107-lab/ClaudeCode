"""AI文書処理ツール - データベースモデル"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class DocaiHistory(Base):
    """文書処理の履歴"""
    __tablename__ = "docai_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    action: Mapped[str] = mapped_column(String(30))  # summarize / translate / qa / extract
    filename: Mapped[str | None] = mapped_column(String(255))
    input_chars: Mapped[int] = mapped_column(Integer, default=0)
    output_chars: Mapped[int] = mapped_column(Integer, default=0)
    model_used: Mapped[str] = mapped_column(String(50), default="gpt-4.1-mini")
    result_preview: Mapped[str | None] = mapped_column(Text)  # 先頭200文字
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
