"""名刺リーダー - AI-OCRサービス"""

import base64
import json

from openai import AsyncOpenAI

from app.config import settings

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _client


async def read_card(image_data: bytes, filename: str) -> dict:
    """名刺画像からAI-OCRで情報抽出"""
    client = _get_client()
    b64 = base64.b64encode(image_data).decode("utf-8")
    ext = filename.rsplit(".", 1)[-1].lower()
    mime = {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "webp": "image/webp",
    }.get(ext, "image/jpeg")

    resp = await client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {
                "role": "system",
                "content": (
                    "あなたは名刺読取の専門家です。名刺画像から以下の情報をJSON形式で抽出してください: "
                    "name(氏名), name_kana(読み仮名、わかれば), company(会社名), department(部署), "
                    "position(役職), email(メールアドレス), phone(電話番号), mobile(携帯番号), "
                    "fax(FAX番号), address(住所), website(URL)。読み取れない項目はnullにしてください。"
                ),
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "この名刺の情報を読み取ってください。"},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                ],
            },
        ],
        temperature=0.1,
        max_tokens=500,
        response_format={"type": "json_object"},
    )
    try:
        return json.loads(resp.choices[0].message.content or "{}")
    except json.JSONDecodeError:
        return {}
