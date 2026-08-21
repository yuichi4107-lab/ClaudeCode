"""議事録ツール - LLM呼び出し"""

from openai import AsyncOpenAI

from app.config import settings

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _client


MAX_INPUT_CHARS = 100_000

ACTIONS = {
    "generate": {
        "name": "議事録生成",
        "system": (
            "あなたはプロの議事録作成者です。会議のメモやテキストから、以下の構造で議事録を作成してください。\n\n"
            "# 議事録\n"
            "## 基本情報\n- 日時:\n- 参加者:\n- 議題:\n\n"
            "## 議題ごとの要約\n（議題ごとに見出しを付けて、議論のポイントを箇条書き）\n\n"
            "## 決定事項\n（番号付きリスト）\n\n"
            "## アクションアイテム\n（担当者・期限があれば明記）\n\n"
            "## 次回予定\n"
            "\n入力テキストに情報が不足している場合は「（記載なし）」としてください。"
        ),
    },
    "action_items": {
        "name": "アクション抽出",
        "system": (
            "あなたは会議の内容分析の専門家です。テキストから以下を抽出してください。\n\n"
            "1. アクションアイテム（やるべきこと）\n"
            "2. 担当者（わかれば）\n"
            "3. 期限（わかれば）\n"
            "4. 優先度（高/中/低）\n\n"
            "表形式（Markdown）で出力してください。"
        ),
    },
    "summary": {
        "name": "要点整理",
        "system": (
            "あなたは会議の要約の専門家です。テキストから以下を簡潔にまとめてください。\n\n"
            "1. 会議の目的（1行）\n"
            "2. 主な議論ポイント（3〜5個の箇条書き）\n"
            "3. 結論・決定事項\n"
            "4. 次のステップ\n\n"
            "全体で300文字以内を目安にしてください。"
        ),
    },
}


async def process_minutes(text: str, action: str, title: str = "") -> str:
    """議事録処理"""
    if len(text) > MAX_INPUT_CHARS:
        raise ValueError(f"テキストが長すぎます（{len(text):,}文字）。上限は{MAX_INPUT_CHARS:,}文字です。")
    if len(text.strip()) < 10:
        raise ValueError("テキストが短すぎます。会議の内容を入力してください。")

    action_def = ACTIONS.get(action)
    if not action_def:
        raise ValueError(f"不明なアクション: {action}")

    user_msg = text
    if title:
        user_msg = f"会議名: {title}\n\n{text}"

    client = _get_client()
    resp = await client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": action_def["system"]},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.3,
        max_tokens=4096,
    )
    return resp.choices[0].message.content or ""
