"""AI画像一括生成ツール - データベースモデル"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ImageGenHistory(Base):
    """画像生成の履歴"""
    __tablename__ = "imagegen_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    prompt: Mapped[str] = mapped_column(Text)
    style: Mapped[str | None] = mapped_column(String(50))
    size: Mapped[str] = mapped_column(String(20), default="1024x1024")
    count: Mapped[int] = mapped_column(Integer, default=1)
    image_urls: Mapped[str | None] = mapped_column(Text)  # JSON array of URLs
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
