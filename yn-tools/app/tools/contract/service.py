"""契約書チェッカー - LLM呼び出し"""

import io

from openai import AsyncOpenAI

from app.config import settings

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _client


MAX_INPUT_CHARS = 100_000

CHECKS = {
    "risk": {
        "name": "リスクチェック",
        "system": (
            "あなたは企業法務の専門家です。契約書を分析し、以下の観点でリスクを洗い出してください。\n"
            "1. 不利な条項（損害賠償の上限なし、一方的な解約権等）\n"
            "2. 曖昧な表現（定義が不明確、解釈の余地が大きい箇所）\n"
            "3. 欠落している条項（秘密保持、知的財産権、紛争解決等）\n"
            "4. 法的リスク（下請法・独禁法等への抵触可能性）\n\n"
            "各リスクについて、重要度（高・中・低）、該当箇所の引用、具体的な修正提案を示してください。"
        ),
    },
    "summary": {
        "name": "契約要約",
        "system": (
            "あなたは企業法務の専門家です。契約書の内容を以下の項目で簡潔に要約してください。\n"
            "- 契約当事者\n- 契約の目的・対象\n- 契約期間\n- 報酬・支払条件\n"
            "- 主要な義務と責任\n- 秘密保持条項\n- 解約条件\n- 損害賠償・免責\n"
            "- その他の重要条項"
        ),
    },
    "clause": {
        "name": "条項解説",
        "system": (
            "あなたは企業法務の専門家です。契約書の各条項を一般的なビジネスパーソンにもわかるよう"
            "平易な日本語で解説してください。法律用語には簡単な説明を添えてください。"
            "特に注意すべき点があれば警告マークで示してください。"
        ),
    },
}


async def extract_text_from_file(content: bytes, filename: str) -> str:
    """ファイルからテキスト抽出"""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext == "pdf":
        try:
            from pypdf import PdfReader
        except ImportError:
            raise ValueError("PDF処理ライブラリが未インストールです")
        reader = PdfReader(io.BytesIO(content))
        pages = [p.extract_text() for p in reader.pages if p.extract_text()]
        if not pages:
            raise ValueError("PDFからテキストを抽出できませんでした")
        return "\n\n".join(pages)

    if ext in ("txt", "md", "doc"):
        return content.decode("utf-8", errors="replace")

    try:
        return content.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        try:
            return content.decode("shift_jis", errors="replace")
        except Exception:
            raise ValueError(f"非対応のファイル形式です: .{ext}")


async def check_contract(text: str, check_type: str) -> str:
    """契約書チェック"""
    if len(text) > MAX_INPUT_CHARS:
        raise ValueError(f"テキストが長すぎます（{len(text):,}文字）。上限は{MAX_INPUT_CHARS:,}文字です。")
    if len(text.strip()) < 20:
        raise ValueError("契約書のテキストが短すぎます。")

    check_def = CHECKS.get(check_type)
    if not check_def:
        raise ValueError(f"不明なチェックタイプ: {check_type}")

    client = _get_client()
    resp = await client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": check_def["system"]},
            {"role": "user", "content": f"以下の契約書を分析してください。\n\n---\n{text}"},
        ],
        temperature=0.2,
        max_tokens=4096,
    )
    return resp.choices[0].message.content or ""
