"""AI文書処理ツール - LLM呼び出し・ファイル解析"""

import io

from openai import AsyncOpenAI

from app.config import settings

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _client


# ---------- ファイル解析 ----------

async def extract_text_from_file(content: bytes, filename: str) -> str:
    """アップロードファイルからテキストを抽出"""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext == "pdf":
        return _extract_pdf(content)
    elif ext in ("txt", "md", "csv", "log", "json", "xml", "html", "yaml", "yml"):
        return content.decode("utf-8", errors="replace")
    else:
        # バイナリでなければテキストとして試行
        try:
            return content.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            try:
                return content.decode("shift_jis", errors="replace")
            except Exception:
                raise ValueError(f"非対応のファイル形式です: .{ext}")


def _extract_pdf(content: bytes) -> str:
    """PDFからテキスト抽出"""
    try:
        from pypdf import PdfReader
    except ImportError:
        raise ValueError("PDF処理ライブラリが未インストールです")

    reader = PdfReader(io.BytesIO(content))
    pages = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            pages.append(text)
    if not pages:
        raise ValueError("PDFからテキストを抽出できませんでした")
    return "\n\n".join(pages)


# ---------- LLM処理 ----------

MAX_INPUT_CHARS = 100_000  # 約25,000トークン


async def summarize(text: str, lang: str = "ja", detail: str = "normal") -> str:
    """テキスト要約"""
    _validate_length(text)

    detail_instruction = {
        "brief": "3〜5行の簡潔な要約",
        "normal": "重要なポイントを箇条書きで整理した要約（10〜20行程度）",
        "detailed": "セクションごとに詳細な要約。見出し付きで構造化",
    }.get(detail, "重要なポイントを箇条書きで整理した要約")

    lang_name = "日本語" if lang == "ja" else "English" if lang == "en" else lang

    return await _call_llm(
        system=f"あなたは文書要約の専門家です。{lang_name}で回答してください。",
        user=f"以下の文書を{detail_instruction}にしてください。\n\n---\n{text}",
    )


async def translate(text: str, target_lang: str = "en") -> str:
    """テキスト翻訳"""
    _validate_length(text)

    lang_map = {
        "ja": "日本語", "en": "English", "zh": "中文",
        "ko": "한국어", "fr": "Français", "de": "Deutsch",
        "es": "Español", "pt": "Português",
    }
    target = lang_map.get(target_lang, target_lang)

    return await _call_llm(
        system=f"あなたはプロの翻訳者です。自然で流暢な{target}に翻訳してください。原文の意味とニュアンスを正確に保ってください。",
        user=f"以下のテキストを{target}に翻訳してください。\n\n---\n{text}",
    )


async def qa(text: str, question: str) -> str:
    """文書に対するQ&A"""
    _validate_length(text)

    return await _call_llm(
        system="あなたは文書分析の専門家です。提供された文書の内容に基づいて、正確に質問に答えてください。文書に書かれていない情報は推測せず、「文書に記載がありません」と回答してください。",
        user=f"【文書】\n{text}\n\n---\n【質問】\n{question}",
    )


async def extract_info(text: str, extract_type: str = "key_points") -> str:
    """情報抽出"""
    _validate_length(text)

    instructions = {
        "key_points": "重要なポイント・キーワード・数値データを箇条書きで抽出してください。",
        "action_items": "タスク・アクションアイテム・ToDo・期限を抽出してください。",
        "contacts": "人名・会社名・メールアドレス・電話番号・住所などの連絡先情報を抽出してください。",
        "table": "文書内のデータを表形式（Markdown）に整理してください。",
    }
    instruction = instructions.get(extract_type, instructions["key_points"])

    return await _call_llm(
        system="あなたはデータ抽出の専門家です。文書から必要な情報を正確に抽出してください。",
        user=f"以下の文書から{instruction}\n\n---\n{text}",
    )


# ---------- 内部ヘルパー ----------

def _validate_length(text: str):
    if len(text) > MAX_INPUT_CHARS:
        raise ValueError(
            f"テキストが長すぎます（{len(text):,}文字）。"
            f"上限は{MAX_INPUT_CHARS:,}文字です。"
        )
    if len(text.strip()) < 10:
        raise ValueError("テキストが短すぎます。")


async def _call_llm(system: str, user: str) -> str:
    client = _get_client()
    resp = await client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.3,
        max_tokens=4096,
    )
    return resp.choices[0].message.content or ""
