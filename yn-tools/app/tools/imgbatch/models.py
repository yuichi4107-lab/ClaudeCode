"""画像一括加工ツール - データベースモデル"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ImgBatchJob(Base):
    """画像バッチ処理ジョブ"""
    __tablename__ = "imgbatch_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    mode: Mapped[str] = mapped_column(String(30))                        # resize_preset / resize_custom / format_convert / bg_remove / crop_center / optimize
    preset_names: Mapped[str | None] = mapped_column(String(500), nullable=True)  # JSON配列
    custom_width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    custom_height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_format: Mapped[str | None] = mapped_column(String(10), nullable=True)  # jpg/png/webp/avif
    input_file_count: Mapped[int] = mapped_column(Integer, default=0)
    output_file_count: Mapped[int] = mapped_column(Integer, default=0)
    zip_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")   # pending/processing/done/error
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
