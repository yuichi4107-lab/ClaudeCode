"""AI議事メモ（音声） - データベースモデル"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class VoiceMinutesHistory(Base):
    """音声議事録の履歴"""
    __tablename__ = "voiceminutes_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    filename: Mapped[str | None] = mapped_column(String(255))
    duration_sec: Mapped[int | None] = mapped_column(Integer)
    transcript_chars: Mapped[int] = mapped_column(Integer, default=0)
    minutes_chars: Mapped[int] = mapped_column(Integer, default=0)
    result_preview: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
