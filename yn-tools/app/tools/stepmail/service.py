"""ステップメール作成ツール - AI生成ロジック"""

import json

from openai import AsyncOpenAI

from app.config import settings

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _client


# ビジネス目的テンプレート定義
BUSINESS_PURPOSE_TEMPLATES: dict[str, dict] = {
    "new_customer": {
        "name": "新規顧客ウェルカム",
        "icon": "👋",
        "recommended_steps": 4,
        "strategy": (
            "1通目: 温かく歓迎し、購入への感謝と期待感を高める。"
            "2通目: 商品の使い方・活用法を具体的に紹介。"
            "3通目: よくある質問・サポート情報を案内。"
            "4通目: 次回購入への特典・アップセルを提案。"
        ),
    },
    "cart_abandon": {
        "name": "カート放棄リカバリ",
        "icon": "🛒",
        "recommended_steps": 3,
        "strategy": (
            "1通目: 「カートに残っています」と気づかせ、購入の背中を押す。"
            "2通目: 商品の価値・他ユーザーの声を強調。"
            "3通目: 最後のきっかけとして期間限定特典や緊急性を訴求。"
        ),
    },
    "seminar": {
        "name": "セミナー集客",
        "icon": "🎤",
        "recommended_steps": 5,
        "strategy": (
            "1通目: セミナーの存在と価値を紹介、興味喚起。"
            "2通目: 登壇者のプロフィール・実績で信頼構築。"
            "3通目: 参加者が得られる具体的なベネフィットを訴求。"
            "4通目: 参加者の声・過去実績で社会的証明。"
            "5通目: 締切・残席の緊急性でCTA強化。"
        ),
    },
    "product_launch": {
        "name": "商品ローンチ",
        "icon": "🚀",
        "recommended_steps": 7,
        "strategy": (
            "1通目: 「近日公開」で期待感を高め、問題提起。"
            "2通目: 現状の問題・悩みを深掘りし共感を得る。"
            "3通目: 解決策の存在を予告、商品のヒントを見せる。"
            "4通目: 商品の全貌を公開、主要な特徴を紹介。"
            "5通目: 導入事例・ユーザーの声で証拠を示す。"
            "6通目: よくある質問・懸念に答えて不安を払拭。"
            "7通目: 販売終了・特典締切の緊急性でCTA最大化。"
        ),
    },
    "repeat": {
        "name": "リピート促進",
        "icon": "🔁",
        "recommended_steps": 3,
        "strategy": (
            "1通目: 前回購入への感謝と次回購入を想起させるコンテンツ。"
            "2通目: 関連商品・アップグレードの提案。"
            "3通目: リピーター限定特典・クーポンで購買意欲を刺激。"
        ),
    },
    "nurture": {
        "name": "リード育成（教育コンテンツ）",
        "icon": "📚",
        "recommended_steps": 7,
        "strategy": (
            "1通目: 読者の悩みに共感し、シリーズの価値を約束する。"
            "2通目: 基礎知識・概念の紹介（教育フェーズ開始）。"
            "3通目: 実践的なヒント・ノウハウの提供。"
            "4通目: よくある失敗パターンと回避策。"
            "5通目: 成功事例・実績の紹介。"
            "6通目: より深い解決策（商品・サービス）の紹介。"
            "7通目: 信頼関係を基盤に具体的なCTAで購買誘導。"
        ),
    },
    "onboarding": {
        "name": "SaaSオンボーディング",
        "icon": "⚙️",
        "recommended_steps": 5,
        "strategy": (
            "1通目: 登録完了の確認と最初のステップ案内。"
            "2通目: 主要機能の使い方（クイックスタートガイド）。"
            "3通目: 便利な機能・活用事例の紹介。"
            "4通目: よくある質問・つまずきポイントのサポート。"
            "5通目: 上位プラン・機能拡張のアップセル提案。"
        ),
    },
    "free_input": {
        "name": "自由設定",
        "icon": "✏️",
        "recommended_steps": 5,
        "strategy": (
            "1通目: 信頼関係の構築と価値の予告。"
            "2通目: 教育コンテンツ・有益な情報提供。"
            "3通目: 具体的なノウハウ・事例の共有。"
            "4通目: 読者の不安・疑問への回答。"
            "最終通: 具体的な行動喚起（CTA）で締め括る。"
        ),
    },
}

TONE_LABELS: dict[str, str] = {
    "formal": "フォーマル（丁寧・格式あるビジネス文体）",
    "casual": "カジュアル（親しみやすく話しかけるような文体）",
    "business": "ビジネス（標準的なビジネスメール文体）",
}

SYSTEM_PROMPT = """\
あなたはプロのメールマーケターです。
依頼された条件に基づき、効果的なステップメールシリーズを日本語で作成してください。

【重要な指示】
- シリーズ全体で一貫したストーリーラインを持たせること
- 各通が前の通を踏まえて自然につながるよう文脈を維持すること
- 指定されたシリーズ構成戦略を厳守すること
- 読者が次のメールを楽しみにするよう、各通の末尾に次回への期待感を持たせること（最終通を除く）

【出力形式】
必ず以下のJSON形式で出力してください。JSON以外の文字は一切含めないこと:
{
  "emails": [
    {
      "step": 1,
      "subject": "件名テキスト（40字以内推奨）",
      "preheader": "プレヘッダーテキスト（40字以内）",
      "body": "本文テキスト（メール本文全体）",
      "cta_text": "CTAボタン文言（20字以内）"
    }
  ]
}
"""


async def generate_series(
    business_purpose: str,
    product_name: str,
    target_audience: str,
    step_count: int,
    tone: str,
    cta_url: str | None = None,
    seller_name: str | None = None,
    extra_info: str | None = None,
) -> list[dict]:
    """GPT-4o-miniでステップメールシリーズを一括生成する"""
    template = BUSINESS_PURPOSE_TEMPLATES.get(
        business_purpose, BUSINESS_PURPOSE_TEMPLATES["free_input"]
    )
    purpose_name = template["name"]
    strategy = template["strategy"]
    tone_desc = TONE_LABELS.get(tone, "ビジネス（標準的なビジネスメール文体）")

    cta_info = f"CTA先URL: {cta_url}" if cta_url else "CTA先URL: 未設定（適切な文言で促してください）"
    sender_info = f"送信者名: {seller_name}" if seller_name else ""
    extra = f"追加情報・USP:\n{extra_info}" if extra_info else ""

    user_message = f"""以下の条件でステップメールシリーズ（全{step_count}通）を作成してください。

【基本情報】
- 目的: {purpose_name}
- 商品・サービス名: {product_name}
- ターゲット: {target_audience}
- 通数: {step_count}通
- 文体・トーン: {tone_desc}
{sender_info}
{cta_info}
{extra}

【シリーズ構成戦略】
{strategy}

【注意事項】
- 全{step_count}通を一括で作成すること
- 各通の本文は500〜800字程度を目安にする
- 読者が実際に行動を起こしたくなるような具体的で魅力的な文章にすること
- プレヘッダーは件名を補完する一文にすること（40字以内）
"""

    client = _get_client()
    resp = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        temperature=0.7,
        max_tokens=8000,
        response_format={"type": "json_object"},
        timeout=120.0,
    )
    raw = resp.choices[0].message.content or "{}"
    data = json.loads(raw)
    emails = data.get("emails", [])
    if emails and len(emails) < step_count:
        # 途中切れの場合も返すが、返った分だけ使う
        pass
    return emails


async def regenerate_single_item(
    business_purpose: str,
    product_name: str,
    target_audience: str,
    tone: str,
    step_number: int,
    total_steps: int,
    context_prev: str | None = None,
    context_next: str | None = None,
    cta_url: str | None = None,
    seller_name: str | None = None,
) -> dict:
    """特定の1通だけを再生成する（前後の文脈を保持）"""
    template = BUSINESS_PURPOSE_TEMPLATES.get(
        business_purpose, BUSINESS_PURPOSE_TEMPLATES["free_input"]
    )
    purpose_name = template["name"]
    tone_desc = TONE_LABELS.get(tone, "ビジネス（標準的なビジネスメール文体）")

    cta_info = f"CTA先URL: {cta_url}" if cta_url else "CTA先URL: 未設定"
    sender_info = f"送信者名: {seller_name}" if seller_name else ""

    prev_context = (
        f"【直前の通（第{step_number - 1}通）の内容】\n{context_prev}\n"
        if context_prev
        else ""
    )
    next_context = (
        f"【直後の通（第{step_number + 1}通）の内容】\n{context_next}\n"
        if context_next
        else ""
    )

    user_message = f"""以下の条件で、ステップメールシリーズの第{step_number}通（全{total_steps}通中）のみを再生成してください。

【シリーズ基本情報】
- 目的: {purpose_name}
- 商品・サービス名: {product_name}
- ターゲット: {target_audience}
- 文体・トーン: {tone_desc}
{sender_info}
{cta_info}

{prev_context}{next_context}

【再生成対象】
第{step_number}通（全{total_steps}通中）

【注意事項】
- 前後の通と文脈が自然につながるようにすること
- 第{step_number}通の役割（{"最初" if step_number == 1 else "最後" if step_number == total_steps else "中盤"}の通）にふさわしい内容にすること
- 本文は500〜800字程度を目安にする

以下のJSON形式で1通分のみ出力してください:
{{
  "emails": [
    {{
      "step": {step_number},
      "subject": "件名テキスト",
      "preheader": "プレヘッダー（40字以内）",
      "body": "本文テキスト",
      "cta_text": "CTAボタン文言"
    }}
  ]
}}
"""

    client = _get_client()
    resp = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        temperature=0.7,
        max_tokens=1500,
        response_format={"type": "json_object"},
    )
    raw = resp.choices[0].message.content or "{}"
    data = json.loads(raw)
    emails = data.get("emails", [])
    return emails[0] if emails else {}
