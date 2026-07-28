"""翻訳ツール - LLM呼び出し"""

from openai import AsyncOpenAI

from app.config import settings

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _client


LANG_MAP = {
    "ja": "日本語", "en": "English", "zh": "中文（簡体字）", "zh-tw": "中文（繁體字）",
    "ko": "한국어", "fr": "Français", "de": "Deutsch",
    "es": "Español", "pt": "Português", "it": "Italiano",
    "ru": "Русский", "ar": "العربية", "hi": "हिन्दी",
    "th": "ภาษาไทย", "vi": "Tiếng Việt", "id": "Bahasa Indonesia",
}

MAX_INPUT_CHARS = 100_000


def detect_source_label(code: str) -> str:
    return LANG_MAP.get(code, code)


def detect_target_label(code: str) -> str:
    return LANG_MAP.get(code, code)


async def translate(text: str, source_lang: str, target_lang: str, tone: str = "natural") -> str:
    """テキスト翻訳"""
    if len(text) > MAX_INPUT_CHARS:
        raise ValueError(f"テキストが長すぎます（{len(text):,}文字）。上限は{MAX_INPUT_CHARS:,}文字です。")
    if len(text.strip()) < 2:
        raise ValueError("翻訳するテキストを入力してください。")

    source = LANG_MAP.get(source_lang, source_lang)
    target = LANG_MAP.get(target_lang, target_lang)

    tone_instruction = {
        "natural": "自然で流暢な",
        "formal": "ビジネス文書にふさわしいフォーマルな",
        "casual": "カジュアルで親しみやすい",
        "technical": "技術文書として正確な",
    }.get(tone, "自然で流暢な")

    client = _get_client()
    resp = await client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {
                "role": "system",
                "content": (
                    f"あなたはプロの翻訳者です。{source}から{target}への翻訳を行います。"
                    f"{tone_instruction}表現で翻訳してください。"
                    "原文の意味・ニュアンス・文体を正確に保ってください。"
                    "翻訳結果のみを出力してください。説明や注釈は不要です。"
                ),
            },
            {"role": "user", "content": text},
        ],
        temperature=0.3,
        max_tokens=4096,
    )
    return resp.choices[0].message.content or ""
