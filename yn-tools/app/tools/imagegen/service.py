"""AI画像一括生成ツール - OpenAI DALL-E / gpt-image-1"""

import json

from openai import AsyncOpenAI

from app.config import settings

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _client


# ---------- スタイルプリセット ----------

STYLE_PRESETS: dict[str, dict] = {
    "none": {"name": "指定なし", "suffix": ""},
    "photo": {"name": "写真風", "suffix": "photorealistic, high quality photograph, professional lighting"},
    "illustration": {"name": "イラスト", "suffix": "digital illustration, clean lines, vibrant colors"},
    "anime": {"name": "アニメ風", "suffix": "anime style, Japanese animation aesthetic"},
    "watercolor": {"name": "水彩画", "suffix": "watercolor painting style, soft brushstrokes, artistic"},
    "minimalist": {"name": "ミニマル", "suffix": "minimalist design, clean, simple, modern"},
    "3d_render": {"name": "3Dレンダー", "suffix": "3D rendered, photorealistic CGI, studio lighting"},
    "flat_design": {"name": "フラットデザイン", "suffix": "flat design, vector art style, bold colors, no shadows"},
    "logo": {"name": "ロゴ・アイコン", "suffix": "logo design, icon, simple, memorable, scalable"},
    "banner": {"name": "バナー・広告", "suffix": "professional advertising banner, eye-catching, commercial quality"},
}


# ---------- 画像生成 ----------

async def generate_images(
    prompt: str,
    style: str = "none",
    size: str = "1024x1024",
    count: int = 1,
) -> list[str]:
    """画像を生成してURL一覧を返す"""

    if not prompt.strip():
        raise ValueError("プロンプトを入力してください。")

    count = min(max(count, 1), 4)  # 1〜4枚

    # スタイルサフィックス追加
    full_prompt = prompt.strip()
    preset = STYLE_PRESETS.get(style, STYLE_PRESETS["none"])
    if preset["suffix"]:
        full_prompt = f"{full_prompt}, {preset['suffix']}"

    client = _get_client()

    urls = []
    for _ in range(count):
        resp = await client.images.generate(
            model="gpt-image-1",
            prompt=full_prompt,
            n=1,
            size=size,
        )
        if resp.data and resp.data[0].url:
            urls.append(resp.data[0].url)

    return urls


def get_style_presets() -> dict:
    """スタイルプリセット一覧"""
    return {k: v["name"] for k, v in STYLE_PRESETS.items()}
