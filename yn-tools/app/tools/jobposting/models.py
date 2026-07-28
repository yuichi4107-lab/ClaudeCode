"""求人票ジェネレーター - データベースモデル"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class JobPosting(Base):
    """求人票"""
    __tablename__ = "jobposting_postings"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    title: Mapped[str] = mapped_column(String(200))           # 保存名（例: 「ホールスタッフ_2026-04」）
    industry_template: Mapped[str] = mapped_column(String(30))
    job_title: Mapped[str] = mapped_column(String(200))
    company_name: Mapped[str] = mapped_column(String(200))
    location: Mapped[str] = mapped_column(String(200))
    salary_type: Mapped[str] = mapped_column(String(20))
    salary_min: Mapped[int] = mapped_column(Integer)
    salary_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    work_hours: Mapped[str] = mapped_column(String(300))
    holidays: Mapped[str | None] = mapped_column(Text, nullable=True)
    qualifications: Mapped[str | None] = mapped_column(Text, nullable=True)
    benefits: Mapped[str | None] = mapped_column(Text, nullable=True)
    pr_points: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_format: Mapped[str] = mapped_column(String(30))    # indeed / townwork / hellowork / general
    generated_text: Mapped[str | None] = mapped_column(Text, nullable=True)  # AI生成結果
    edited_text: Mapped[str | None] = mapped_column(Text, nullable=True)     # ユーザー編集後
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
