"""経費トラッカー - AI読取・分析サービス"""

from openai import AsyncOpenAI
import base64
from app.config import settings

_client: AsyncOpenAI | None = None

def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _client


async def read_receipt(image_data: bytes, filename: str) -> dict:
    """レシート画像からAI-OCRで情報抽出"""
    client = _get_client()
    b64 = base64.b64encode(image_data).decode("utf-8")
    ext = filename.rsplit(".", 1)[-1].lower()
    mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}.get(ext, "image/jpeg")

    resp = await client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": "あなたはレシート読取の専門家です。画像から以下の情報をJSON形式で抽出してください: date(YYYY-MM-DD), category(交通費/交際費/消耗品費/通信費/地代家賃/水道光熱費/広告宣伝費/雑費 のいずれか), description(内容の簡潔な説明), amount(数値のみ、円), store(店名)。読み取れない項目はnullにしてください。"},
            {"role": "user", "content": [
                {"type": "text", "text": "このレシートの情報を読み取ってください。"},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
            ]},
        ],
        temperature=0.1,
        max_tokens=500,
        response_format={"type": "json_object"},
    )
    import json
    try:
        return json.loads(resp.choices[0].message.content or "{}")
    except json.JSONDecodeError:
        return {}


async def generate_monthly_report(expenses: list[dict]) -> str:
    """月次経費レポートをAI生成"""
    if not expenses:
        return "この期間の経費データがありません。"

    client = _get_client()
    expense_text = "\n".join(
        f"- {e['date']} | {e['category']} | {e['description']} | ¥{e['amount']:,}"
        for e in expenses
    )

    resp = await client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": "あなたは経理の専門家です。経費データを分析し、カテゴリ別集計・前月比較のポイント・経費削減の提案を含む月次レポートを作成してください。Markdown形式で出力。"},
            {"role": "user", "content": f"以下の経費データを分析してレポートを作成してください:\n\n{expense_text}"},
        ],
        temperature=0.3,
        max_tokens=2048,
    )
    return resp.choices[0].message.content or ""
