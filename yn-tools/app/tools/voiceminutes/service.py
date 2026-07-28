"""AI議事メモ（音声） - Whisper文字起こし+議事録生成"""

import io
from openai import AsyncOpenAI

from app.config import settings

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _client


async def transcribe_audio(audio_data: bytes, filename: str) -> str:
    """音声ファイルをWhisperで文字起こし"""
    client = _get_client()

    audio_file = io.BytesIO(audio_data)
    audio_file.name = filename

    transcript = await client.audio.transcriptions.create(
        model="whisper-1",
        file=audio_file,
        language="ja",
        response_format="text",
    )
    return transcript


async def generate_minutes(transcript: str, meeting_title: str = "", participants: str = "") -> str:
    """文字起こしテキストから議事録を生成"""
    client = _get_client()

    context_parts = []
    if meeting_title:
        context_parts.append(f"会議名: {meeting_title}")
    if participants:
        context_parts.append(f"参加者: {participants}")
    context = "\n".join(context_parts)

    resp = await client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": f"あなたは議事録作成の専門家です。音声の文字起こしテキストから、構造化された議事録を作成してください。\n{context}\n\n以下の構成で:\n\n【議事録】\n■ 会議概要\n■ 議題・討議内容\n（項目ごとに整理）\n■ 決定事項\n■ アクションアイテム\n（担当者・期限があれば記載）\n■ 次回予定\n\n話し言葉を適切な書き言葉に変換し、冗長な部分は要約してください。"},
            {"role": "user", "content": f"以下の文字起こしテキストから議事録を作成してください:\n\n{transcript}"},
        ],
        temperature=0.3,
        max_tokens=4096,
    )
    return resp.choices[0].message.content or ""
