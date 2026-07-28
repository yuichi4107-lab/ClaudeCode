"""SNS投稿スケジューラー - AI文案生成"""

from openai import AsyncOpenAI

from app.config import settings

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _client


PLATFORMS = {
    "x": {"name": "X (Twitter)", "max_chars": 280, "icon": "X"},
    "instagram": {"name": "Instagram", "max_chars": 2200, "icon": "IG"},
    "facebook": {"name": "Facebook", "max_chars": 5000, "icon": "FB"},
    "threads": {"name": "Threads", "max_chars": 500, "icon": "TH"},
    "linkedin": {"name": "LinkedIn", "max_chars": 3000, "icon": "LI"},
}


async def generate_post(topic: str, platform: str, tone: str = "casual") -> dict:
    """AI投稿文案生成"""
    if len(topic.strip()) < 3:
        raise ValueError("トピックを入力してください。")

    pf = PLATFORMS.get(platform, PLATFORMS["x"])
    max_chars = pf["max_chars"]

    tone_map = {
        "casual": "カジュアルで親しみやすい",
        "professional": "プロフェッショナルでビジネス向き",
        "humorous": "ユーモアがあって面白い",
        "inspiring": "インスピレーションを与える感動的な",
    }
    tone_desc = tone_map.get(tone, tone_map["casual"])

    client = _get_client()
    resp = await client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {
                "role": "system",
                "content": (
                    f"あなたはSNSマーケティングの専門家です。"
                    f"{pf['name']}向けの投稿文を作成してください。"
                    f"文字数は{max_chars}文字以内。{tone_desc}トーンで書いてください。"
                    f"投稿本文とハッシュタグを分けて出力してください。"
                    f"\n\n出力形式:\n本文:\n（投稿本文）\n\nハッシュタグ:\n（#タグ1 #タグ2 ...）"
                ),
            },
            {"role": "user", "content": f"トピック: {topic}"},
        ],
        temperature=0.7,
        max_tokens=1000,
    )

    result = resp.choices[0].message.content or ""

    # Parse content and hashtags
    content = result
    hashtags = ""
    if "ハッシュタグ:" in result:
        parts = result.split("ハッシュタグ:")
        content = parts[0].replace("本文:", "").strip()
        hashtags = parts[1].strip()
    elif "本文:" in result:
        content = result.replace("本文:", "").strip()

    return {"content": content, "hashtags": hashtags}
