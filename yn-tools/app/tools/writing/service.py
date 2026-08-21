"""ライティングアシスタント - LLM呼び出し"""

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
    "proofread": {
        "name": "校正",
        "system": "あなたはプロの校正者です。文法・誤字脱字・句読点のミスを修正してください。修正箇所は【】で囲んで示してください。元の文体やトーンは変えないでください。",
        "user": "以下の文章を校正してください。\n\n{text}",
    },
    "rewrite": {
        "name": "リライト",
        "system": "あなたはプロのライターです。文章の意味を保ちながら、より読みやすく魅力的な文章に書き直してください。",
        "user": "以下の文章をリライトしてください。\n\n{text}",
    },
    "shorten": {
        "name": "要約・短縮",
        "system": "あなたはプロの編集者です。文章の核心を保ちながら、簡潔に短縮してください。情報の欠落がないよう注意してください。",
        "user": "以下の文章を簡潔に短縮してください。\n\n{text}",
    },
    "expand": {
        "name": "膨らませる",
        "system": "あなたはプロのライターです。文章の内容を膨らませて、より詳細で具体的な文章にしてください。元の趣旨から逸脱しないでください。",
        "user": "以下の文章をより詳細に膨らませてください。\n\n{text}",
    },
    "tone": {
        "name": "トーン変換",
        "system": "あなたはプロのライターです。文章の意味を変えずに、指定されたトーンに変換してください。",
        "user": "以下の文章を「{tone}」なトーンに変換してください。\n\n{text}",
    },
}


async def process(text: str, action: str, tone: str = "") -> str:
    """文章処理"""
    if len(text) > MAX_INPUT_CHARS:
        raise ValueError(f"テキストが長すぎます（{len(text):,}文字）。上限は{MAX_INPUT_CHARS:,}文字です。")
    if len(text.strip()) < 5:
        raise ValueError("テキストが短すぎます。")

    action_def = ACTIONS.get(action)
    if not action_def:
        raise ValueError(f"不明なアクション: {action}")

    user_prompt = action_def["user"].format(text=text, tone=tone)

    client = _get_client()
    resp = await client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": action_def["system"]},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.3,
        max_tokens=4096,
    )
    return resp.choices[0].message.content or ""
