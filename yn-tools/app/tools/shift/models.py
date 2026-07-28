"""シフト作成アプリ - データベースモデル"""

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ShiftEmployee(Base):
    """従業員マスタ"""
    __tablename__ = "shift_employees"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(20), default="part_time")  # full_time / part_time / arbeit
    hourly_wage: Mapped[int | None] = mapped_column(Integer)
    available_days: Mapped[str] = mapped_column(String(20), default="0123456")  # 0=月〜6=日
    available_start: Mapped[str] = mapped_column(String(5), default="09:00")
    available_end: Mapped[str] = mapped_column(String(5), default="22:00")
    max_hours_per_week: Mapped[int] = mapped_column(Integer, default=40)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ShiftTemplate(Base):
    """シフトテンプレート（早番/遅番等）"""
    __tablename__ = "shift_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(50))
    start_time: Mapped[str] = mapped_column(String(5))  # HH:MM
    end_time: Mapped[str] = mapped_column(String(5))    # HH:MM
    break_minutes: Mapped[int] = mapped_column(Integer, default=60)
    color: Mapped[str] = mapped_column(String(7), default="#3B82F6")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ShiftSchedule(Base):
    """シフト表ヘッダー"""
    __tablename__ = "shift_schedules"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(100))
    year_month: Mapped[str] = mapped_column(String(7))  # YYYY-MM
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft / published
    ai_generated: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ShiftRequest(Base):
    """シフト希望（休み希望・出勤希望等）"""
    __tablename__ = "shift_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    schedule_id: Mapped[int] = mapped_column(Integer, index=True)
    employee_id: Mapped[int] = mapped_column(Integer, index=True)
    work_date: Mapped[date] = mapped_column(Date)
    request_type: Mapped[str] = mapped_column(String(20))  # day_off / prefer_work / prefer_template
    template_id: Mapped[int | None] = mapped_column(Integer)  # prefer_templateの場合のみ
    note: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("ix_shift_requests_schedule_date", "schedule_id", "work_date"),
    )


class ShiftAssignment(Base):
    """シフト割り当て明細"""
    __tablename__ = "shift_assignments"

    id: Mapped[int] = mapped_column(primary_key=True)
    schedule_id: Mapped[int] = mapped_column(Integer, index=True)
    employee_id: Mapped[int] = mapped_column(Integer, index=True)
    template_id: Mapped[int | None] = mapped_column(Integer)  # NULL=休み
    work_date: Mapped[date] = mapped_column(Date)
    custom_start: Mapped[str | None] = mapped_column(String(5))
    custom_end: Mapped[str | None] = mapped_column(String(5))
    note: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("ix_shift_assignments_schedule_date", "schedule_id", "work_date"),
    )
