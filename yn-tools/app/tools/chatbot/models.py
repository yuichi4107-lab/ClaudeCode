"""AIチャットボットビルダー - データベースモデル"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _gen_bot_id() -> str:
    return uuid.uuid4().hex[:12]


class Chatbot(Base):
    """チャットボット定義"""
    __tablename__ = "chatbots"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    bot_id: Mapped[str] = mapped_column(String(20), unique=True, index=True, default=_gen_bot_id)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text, default="")
    system_prompt: Mapped[str] = mapped_column(Text)  # ボットの性格・役割
    knowledge: Mapped[str] = mapped_column(Text, default="")  # ナレッジベース（テキスト）
    welcome_message: Mapped[str] = mapped_column(String(500), default="こんにちは！何かお手伝いできることはありますか？")
    theme_color: Mapped[str] = mapped_column(String(7), default="#4F46E5")  # ウィジェットの色
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    total_messages: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class ChatMessage(Base):
    """チャット履歴"""
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    bot_id: Mapped[str] = mapped_column(String(20), index=True)
    session_id: Mapped[str] = mapped_column(String(40), index=True)
    role: Mapped[str] = mapped_column(String(10))  # user / assistant
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
