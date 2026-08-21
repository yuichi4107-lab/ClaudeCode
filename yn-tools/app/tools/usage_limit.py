"""月次利用制限チェック - 全AIツール共通"""

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

# ツール別の月次制限
MONTHLY_LIMITS: dict[str, int] = {
    "imagegen": 10,    # 枚数（生成枚数の合計）
    "docai": 30,       # 回数
    "contentgen": 30,  # 回数
    "webresearch": 20, # 回数
    "chatbot": 500,    # メッセージ数（ボット全体合計）
    "translate": 30,   # 回数
    "writing": 30,     # 回数
    "contract": 20,    # 回数
    "minutes": 30,     # 回数
    "expense": 20,     # 回数（AI読取・レポート生成）
    "seocheck": 20,    # 回数
    "dailyreport": 30, # 回数
    "cardreader": 30,  # 回数（AI読取）
    "voiceminutes": 10, # 回数（音声議事録）
    "jobposting": 30,   # 回数（求人票生成）
    "dataclean": 20,    # 回数（データクリーニング）
    "imgbatch": 20,     # 回数（画像一括加工）
    "stepmail": 20,     # 回数（ステップメール生成）
    "legalgen": 20,     # 回数（契約書・利用規約生成）
}

# ユーザー向け表示単位
UNIT_LABELS: dict[str, str] = {
    "imagegen": "枚",
    "docai": "回",
    "contentgen": "回",
    "webresearch": "回",
    "chatbot": "メッセージ",
    "translate": "回",
    "writing": "回",
    "contract": "回",
    "minutes": "回",
    "expense": "回",
    "seocheck": "回",
    "dailyreport": "回",
    "cardreader": "回",
    "voiceminutes": "回",
    "jobposting": "回",
    "dataclean": "回",
    "imgbatch": "回",
    "stepmail": "回",
    "legalgen": "回",
}


def month_start() -> datetime:
    """今月1日 00:00:00 UTC を返す（timezone-naive、DB の TIMESTAMP WITHOUT TIME ZONE に合わせる）"""
    now = datetime.utcnow()
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def get_limit(tool: str) -> int:
    return MONTHLY_LIMITS.get(tool, 0)


def get_unit(tool: str) -> str:
    return UNIT_LABELS.get(tool, "回")


async def get_monthly_usage(db: AsyncSession, user_id: int, tool: str) -> int:
    """今月の利用量を返す"""
    start = month_start()

    if tool == "imagegen":
        from app.tools.imagegen.models import ImageGenHistory
        r = await db.execute(
            select(func.coalesce(func.sum(ImageGenHistory.count), 0))
            .where(ImageGenHistory.user_id == user_id, ImageGenHistory.created_at >= start)
        )
        return int(r.scalar() or 0)

    if tool == "docai":
        from app.tools.docai.models import DocaiHistory
        r = await db.execute(
            select(func.count(DocaiHistory.id))
            .where(DocaiHistory.user_id == user_id, DocaiHistory.created_at >= start)
        )
        return int(r.scalar() or 0)

    if tool == "contentgen":
        from app.tools.contentgen.models import ContentGenHistory
        r = await db.execute(
            select(func.count(ContentGenHistory.id))
            .where(ContentGenHistory.user_id == user_id, ContentGenHistory.created_at >= start)
        )
        return int(r.scalar() or 0)

    if tool == "webresearch":
        from app.tools.webresearch.models import WebResearchHistory
        r = await db.execute(
            select(func.count(WebResearchHistory.id))
            .where(WebResearchHistory.user_id == user_id, WebResearchHistory.created_at >= start)
        )
        return int(r.scalar() or 0)

    if tool == "translate":
        from app.tools.translate.models import TranslateHistory
        r = await db.execute(
            select(func.count(TranslateHistory.id))
            .where(TranslateHistory.user_id == user_id, TranslateHistory.created_at >= start)
        )
        return int(r.scalar() or 0)

    if tool == "writing":
        from app.tools.writing.models import WritingHistory
        r = await db.execute(
            select(func.count(WritingHistory.id))
            .where(WritingHistory.user_id == user_id, WritingHistory.created_at >= start)
        )
        return int(r.scalar() or 0)

    if tool == "contract":
        from app.tools.contract.models import ContractHistory
        r = await db.execute(
            select(func.count(ContractHistory.id))
            .where(ContractHistory.user_id == user_id, ContractHistory.created_at >= start)
        )
        return int(r.scalar() or 0)

    if tool == "minutes":
        from app.tools.minutes.models import MinutesHistory
        r = await db.execute(
            select(func.count(MinutesHistory.id))
            .where(MinutesHistory.user_id == user_id, MinutesHistory.created_at >= start)
        )
        return int(r.scalar() or 0)

    if tool == "expense":
        from app.tools.expense.models import Expense
        r = await db.execute(
            select(func.count(Expense.id))
            .where(Expense.user_id == user_id, Expense.created_at >= start)
        )
        return int(r.scalar() or 0)

    if tool == "seocheck":
        from app.tools.seocheck.models import SeoCheckHistory
        r = await db.execute(
            select(func.count(SeoCheckHistory.id))
            .where(SeoCheckHistory.user_id == user_id, SeoCheckHistory.created_at >= start)
        )
        return int(r.scalar() or 0)

    if tool == "dailyreport":
        from app.tools.dailyreport.models import DailyReportHistory
        r = await db.execute(
            select(func.count(DailyReportHistory.id))
            .where(DailyReportHistory.user_id == user_id, DailyReportHistory.created_at >= start)
        )
        return int(r.scalar() or 0)

    if tool == "cardreader":
        from app.tools.cardreader.models import BusinessCard
        r = await db.execute(
            select(func.count(BusinessCard.id))
            .where(BusinessCard.user_id == user_id, BusinessCard.created_at >= start)
        )
        return int(r.scalar() or 0)

    if tool == "voiceminutes":
        from app.tools.voiceminutes.models import VoiceMinutesHistory
        r = await db.execute(
            select(func.count(VoiceMinutesHistory.id))
            .where(VoiceMinutesHistory.user_id == user_id, VoiceMinutesHistory.created_at >= start)
        )
        return int(r.scalar() or 0)

    if tool == "jobposting":
        from app.tools.jobposting.models import JobPosting
        r = await db.execute(
            select(func.count(JobPosting.id))
            .where(JobPosting.user_id == user_id, JobPosting.created_at >= start)
        )
        return int(r.scalar() or 0)

    if tool == "dataclean":
        from app.tools.dataclean.models import DataCleanJob
        r = await db.execute(
            select(func.count(DataCleanJob.id))
            .where(
                DataCleanJob.user_id == user_id,
                DataCleanJob.created_at >= start,
                DataCleanJob.status == "done",
            )
        )
        return int(r.scalar() or 0)

    if tool == "imgbatch":
        from app.tools.imgbatch.models import ImgBatchJob
        r = await db.execute(
            select(func.count(ImgBatchJob.id))
            .where(
                ImgBatchJob.user_id == user_id,
                ImgBatchJob.created_at >= start,
                ImgBatchJob.status == "done",
            )
        )
        return int(r.scalar() or 0)

    if tool == "stepmail":
        from app.tools.stepmail.models import StepMailSeries
        r = await db.execute(
            select(func.count(StepMailSeries.id))
            .where(
                StepMailSeries.user_id == user_id,
                StepMailSeries.created_at >= start,
                StepMailSeries.status == "generated",
            )
        )
        return int(r.scalar() or 0)

    if tool == "legalgen":
        from app.tools.legalgen.models import LegalDocument
        r = await db.execute(
            select(func.count(LegalDocument.id))
            .where(LegalDocument.user_id == user_id, LegalDocument.created_at >= start)
        )
        return int(r.scalar() or 0)

    if tool == "chatbot":
        from app.tools.chatbot.models import Chatbot, ChatMessage
        r = await db.execute(
            select(func.count(ChatMessage.id))
            .join(Chatbot, ChatMessage.bot_id == Chatbot.bot_id)
            .where(
                Chatbot.user_id == user_id,
                ChatMessage.role == "user",
                ChatMessage.created_at >= start,
            )
        )
        return int(r.scalar() or 0)

    return 0


def limit_error(tool: str, used: int, limit: int, amount: int = 1) -> str | None:
    """制限超過なら日本語エラー文字列を返す。問題なければ None"""
    remaining = limit - used
    unit = get_unit(tool)
    if remaining <= 0:
        return f"今月の利用上限（{limit}{unit}）に達しました。来月1日にリセットされます。"
    if remaining < amount:
        return f"今月の残り利用可能数は {remaining}{unit} です（上限: {limit}{unit}）。"
    return None
