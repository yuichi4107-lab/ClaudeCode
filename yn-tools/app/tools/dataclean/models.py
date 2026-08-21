"""データクリーニングツール - データベースモデル"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class DataCleanJob(Base):
    """データクリーニングジョブ"""
    __tablename__ = "dataclean_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    file_size_bytes: Mapped[int] = mapped_column(Integer)
    row_count_before: Mapped[int] = mapped_column(Integer, default=0)
    row_count_after: Mapped[int] = mapped_column(Integer, default=0)
    col_count: Mapped[int] = mapped_column(Integer, default=0)
    changed_cells: Mapped[int] = mapped_column(Integer, default=0)
    options_applied: Mapped[str] = mapped_column(String(500))        # JSON配列文字列
    output_path: Mapped[str | None] = mapped_column(String(500), nullable=True)  # サーバー側一時ファイルパス
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending/done/error
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
