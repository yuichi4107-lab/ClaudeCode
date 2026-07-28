"""日報ジェネレーター - AI生成サービス"""

from openai import AsyncOpenAI

from app.config import settings

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _client


async def generate_daily_report(memo: str, report_date: str, department: str = "") -> str:
    """作業メモから日報を生成"""
    client = _get_client()
    dept_info = f"所属: {department}\n" if department else ""

    resp = await client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": f"あなたはビジネス文書作成の専門家です。作業メモから、上司に提出する日報を作成してください。以下の構成で、簡潔で読みやすいフォーマットにしてください:\n\n【日報】\n日付: {report_date}\n{dept_info}\n■ 本日の業務内容\n（箇条書きで各タスクを整理）\n\n■ 進捗・成果\n（具体的な成果を記述）\n\n■ 課題・懸念事項\n（あれば記述、なければ「特になし」）\n\n■ 明日の予定\n（メモに言及があれば記述）"},
            {"role": "user", "content": f"以下の作業メモから日報を作成してください:\n\n{memo}"},
        ],
        temperature=0.3,
        max_tokens=2048,
    )
    return resp.choices[0].message.content or ""


async def generate_weekly_report(memo: str, week_period: str, department: str = "") -> str:
    """作業メモから週報を生成"""
    client = _get_client()
    dept_info = f"所属: {department}\n" if department else ""

    resp = await client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": f"あなたはビジネス文書作成の専門家です。作業メモから、上司に提出する週報を作成してください。以下の構成で:\n\n【週報】\n期間: {week_period}\n{dept_info}\n■ 今週の業務サマリー\n（主要な業務を要約）\n\n■ 各日の業務内容\n（曜日ごとに整理、メモにあれば）\n\n■ 今週の成果\n（KPI、完了タスク等）\n\n■ 課題・来週の対応事項\n\n■ 来週の予定"},
            {"role": "user", "content": f"以下の作業メモから週報を作成してください:\n\n{memo}"},
        ],
        temperature=0.3,
        max_tokens=3000,
    )
    return resp.choices[0].message.content or ""
