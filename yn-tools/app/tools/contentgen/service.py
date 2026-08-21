"""AIコンテンツ生成ツール - LLM呼び出し"""

from openai import AsyncOpenAI

from app.config import settings

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _client


# ---------- 組み込みテンプレート ----------

BUILTIN_TEMPLATES: dict[str, dict] = {
    # --- SNS投稿 ---
    "sns_instagram": {
        "name": "Instagram投稿",
        "content_type": "sns",
        "system": (
            "あなたはInstagramマーケティングの専門家です。"
            "エンゲージメントの高い日本語の投稿文を作成してください。"
            "ハッシュタグを10〜15個含め、絵文字を適度に使い、改行で読みやすくしてください。"
        ),
        "template": "以下のテーマでInstagram投稿を作成してください。\nテーマ: {topic}\nターゲット: {target}\nトーン: {tone}",
    },
    "sns_x": {
        "name": "X (Twitter) 投稿",
        "content_type": "sns",
        "system": (
            "あなたはXマーケティングの専門家です。"
            "140文字以内でインパクトのある日本語ポストを作成してください。"
            "バリエーションを3パターン提案してください。"
        ),
        "template": "以下のテーマでXの投稿を3パターン作成してください。\nテーマ: {topic}\nトーン: {tone}",
    },
    "sns_facebook": {
        "name": "Facebook投稿",
        "content_type": "sns",
        "system": (
            "あなたはFacebookマーケティングの専門家です。"
            "信頼感のある、シェアされやすい日本語の投稿文を作成してください。"
        ),
        "template": "以下のテーマでFacebook投稿を作成してください。\nテーマ: {topic}\nターゲット: {target}\nトーン: {tone}",
    },
    "sns_threads": {
        "name": "Threads投稿",
        "content_type": "sns",
        "system": (
            "あなたはThreadsでのコミュニケーション専門家です。"
            "カジュアルで共感を呼ぶ日本語投稿を作成してください。"
            "500文字以内で、読みやすい文体にしてください。"
        ),
        "template": "以下のテーマでThreads投稿を作成してください。\nテーマ: {topic}\nトーン: {tone}",
    },
    # --- ブログ記事 ---
    "blog_seo": {
        "name": "SEOブログ記事",
        "content_type": "blog",
        "system": (
            "あなたはSEOライティングの専門家です。"
            "検索上位を狙えるブログ記事を作成してください。"
            "H2/H3見出し構造、メタディスクリプション、内部リンク提案を含めてください。"
        ),
        "template": "以下のキーワード/テーマでSEO記事を作成してください。\nキーワード: {topic}\nターゲット読者: {target}\n文字数目安: {length}文字",
    },
    "blog_column": {
        "name": "コラム・オピニオン記事",
        "content_type": "blog",
        "system": (
            "あなたはプロのコラムニストです。"
            "読者の興味を引く導入、説得力のある本文、印象的な結びで構成してください。"
        ),
        "template": "以下のテーマでコラムを書いてください。\nテーマ: {topic}\nトーン: {tone}\n文字数目安: {length}文字",
    },
    # --- 広告コピー ---
    "ad_copy": {
        "name": "広告コピー",
        "content_type": "ad",
        "system": (
            "あなたはコピーライターです。"
            "キャッチコピー、ボディコピー、CTA（行動喚起）をセットで作成してください。"
            "5パターンのバリエーションを提案してください。"
        ),
        "template": "以下の商品/サービスの広告コピーを5パターン作成してください。\n商品/サービス: {topic}\nターゲット: {target}\nUSP（強み）: {usp}",
    },
    "ad_lp": {
        "name": "LP（ランディングページ）構成",
        "content_type": "ad",
        "system": (
            "あなたはLPコンバージョン最適化の専門家です。"
            "ファーストビュー、問題提起、解決策、ベネフィット、社会的証明、CTA"
            "の構成でLP文章を作成してください。"
        ),
        "template": "以下のサービスのLP文章を作成してください。\nサービス名: {topic}\nターゲット: {target}\n主な特徴: {usp}",
    },
    # --- ビジネスメール ---
    "email_sales": {
        "name": "営業メール",
        "content_type": "email",
        "system": (
            "あなたはBtoBの営業メールライティングの専門家です。"
            "開封率・返信率の高いメールを作成してください。"
            "件名と本文を3パターン提案してください。"
        ),
        "template": "以下のサービスの営業メールを3パターン作成してください。\nサービス: {topic}\n送信先: {target}\nメリット: {usp}",
    },
    "email_followup": {
        "name": "フォローアップメール",
        "content_type": "email",
        "system": (
            "あなたはビジネスコミュニケーションの専門家です。"
            "丁寧だが簡潔なフォローアップメールを作成してください。"
        ),
        "template": "以下の状況でフォローアップメールを作成してください。\n状況: {topic}\n相手: {target}",
    },
    # --- 自由生成 ---
    "free_custom": {
        "name": "カスタム生成",
        "content_type": "free",
        "system": (
            "あなたはプロのライターです。"
            "ユーザーの指示に従って、高品質なテキストコンテンツを作成してください。"
        ),
        "template": "{topic}",
    },
}


# ---------- 生成処理 ----------

async def generate_content(
    template_key: str,
    topic: str,
    target: str = "",
    tone: str = "",
    usp: str = "",
    length: str = "1000",
    custom_system: str = "",
    custom_template: str = "",
) -> str:
    """テンプレートに基づいてコンテンツを生成"""

    if template_key == "custom" and custom_system and custom_template:
        system_prompt = custom_system
        user_prompt = custom_template.replace("{topic}", topic)
    elif template_key in BUILTIN_TEMPLATES:
        tmpl = BUILTIN_TEMPLATES[template_key]
        system_prompt = tmpl["system"]
        user_prompt = tmpl["template"].format(
            topic=topic,
            target=target or "一般",
            tone=tone or "プロフェッショナル",
            usp=usp or "未指定",
            length=length or "1000",
        )
    else:
        raise ValueError(f"不明なテンプレート: {template_key}")

    return await _call_llm(system_prompt, user_prompt)


async def _call_llm(system: str, user: str) -> str:
    client = _get_client()
    resp = await client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.7,
        max_tokens=4096,
    )
    return resp.choices[0].message.content or ""
