"""タスクマネージャー - データモデル"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="todo")  # todo / doing / done
    priority: Mapped[str] = mapped_column(String(10), default="medium")  # high / medium / low
    due_date: Mapped[str | None] = mapped_column(String(10), nullable=True)  # YYYY-MM-DD
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
