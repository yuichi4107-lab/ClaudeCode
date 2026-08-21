"""翻訳ツール - データベースモデル"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TranslateHistory(Base):
    """翻訳履歴"""
    __tablename__ = "translate_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    source_lang: Mapped[str] = mapped_column(String(10))
    target_lang: Mapped[str] = mapped_column(String(10))
    input_chars: Mapped[int] = mapped_column(Integer, default=0)
    output_chars: Mapped[int] = mapped_column(Integer, default=0)
    result_preview: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
