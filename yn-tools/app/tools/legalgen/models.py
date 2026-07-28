"""契約書・利用規約自動作成ツール - データベースモデル"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class LegalDocument(Base):
    """生成済み法的文書"""
    __tablename__ = "legalgen_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    doc_type: Mapped[str] = mapped_column(String(30))           # commission/nda/sale/tos/privacy/employment/rent
    title: Mapped[str] = mapped_column(String(300))             # 自動生成（例: 「業務委託契約書_株式会社ABC_2026-04」）
    party_a_name: Mapped[str] = mapped_column(String(200))
    party_b_name: Mapped[str] = mapped_column(String(200))
    effective_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    input_params: Mapped[str] = mapped_column(Text)             # 全入力パラメータJSON
    generated_text: Mapped[str] = mapped_column(Text)           # AI生成結果（Markdown）
    edited_text: Mapped[str | None] = mapped_column(Text, nullable=True)  # ユーザー編集後
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
