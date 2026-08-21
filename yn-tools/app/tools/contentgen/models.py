"""AIコンテンツ生成ツール - データベースモデル"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ContentGenHistory(Base):
    """コンテンツ生成の履歴"""
    __tablename__ = "contentgen_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    content_type: Mapped[str] = mapped_column(String(30))  # sns / blog / ad / email / free
    platform: Mapped[str | None] = mapped_column(String(30))  # instagram / x / facebook 等
    topic: Mapped[str] = mapped_column(String(500))
    output_chars: Mapped[int] = mapped_column(Integer, default=0)
    result_preview: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ContentTemplate(Base):
    """ユーザーカスタムテンプレート"""
    __tablename__ = "contentgen_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(100))
    content_type: Mapped[str] = mapped_column(String(30))
    system_prompt: Mapped[str] = mapped_column(Text)
    user_prompt_template: Mapped[str] = mapped_column(Text)  # {topic}等のプレースホルダ
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
