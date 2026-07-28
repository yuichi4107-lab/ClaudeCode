"""予約管理 - データベースモデル"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class BookingForm(Base):
    """予約フォーム"""
    __tablename__ = "booking_forms"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    form_id: Mapped[str] = mapped_column(String(36), unique=True, default=lambda: str(uuid.uuid4())[:8])
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    duration_min: Mapped[int] = mapped_column(Integer, default=60)
    available_days: Mapped[str] = mapped_column(String(50), default="mon,tue,wed,thu,fri")
    available_start: Mapped[str] = mapped_column(String(5), default="09:00")
    available_end: Mapped[str] = mapped_column(String(5), default="18:00")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Booking(Base):
    """予約"""
    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(primary_key=True)
    form_id: Mapped[str] = mapped_column(String(36), index=True)
    guest_name: Mapped[str] = mapped_column(String(255))
    guest_email: Mapped[str] = mapped_column(String(255))
    guest_note: Mapped[str | None] = mapped_column(Text)
    booked_date: Mapped[str] = mapped_column(String(10))  # YYYY-MM-DD
    booked_time: Mapped[str] = mapped_column(String(5))    # HH:MM
    status: Mapped[str] = mapped_column(String(20), default="confirmed")  # confirmed / canceled
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
