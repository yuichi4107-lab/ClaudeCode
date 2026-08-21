"""求人票ジェネレーター - AI生成ロジック"""

from openai import AsyncOpenAI

from app.config import settings

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _client


# 業種テンプレート定義
INDUSTRY_TEMPLATES: dict[str, dict] = {
    "restaurant": {
        "name": "飲食店ホール・キッチン",
        "qualifications_default": "未経験歓迎。笑顔でお客様に接することができる方。週3日以上勤務できる方。",
        "benefits_default": "まかない無料。交通費支給（上限あり）。シフト制で調整可能。社会保険完備（週30h以上）。",
        "pr_points_default": "活気あるチームで働けます。未経験から料理・接客を学べる環境です。経験者は時給優遇あり。",
    },
    "care": {
        "name": "介護職・ヘルパー",
        "qualifications_default": "介護職員初任者研修修了（歓迎）。未経験・無資格でも応募可。思いやりのある方歓迎。",
        "benefits_default": "資格取得支援制度あり。介護手当支給。夜勤手当あり。社会保険完備。育休・産休取得実績あり。",
        "pr_points_default": "資格取得費用を全額補助します。ベテランスタッフが丁寧に指導します。地域密着で安定した職場環境です。",
    },
    "construction": {
        "name": "建設・土木作業員",
        "qualifications_default": "要普通自動車免許（AT限定可）。体力に自信のある方。経験者優遇・未経験でも資格取得支援あり。",
        "benefits_default": "作業着・安全靴支給。各種手当あり（資格手当・現場手当等）。社会保険完備。退職金制度あり。",
        "pr_points_default": "国家資格取得を支援します。経験・スキルに応じて給与UP。安定した公共工事が中心で長期就業できます。",
    },
    "office": {
        "name": "一般事務・経理",
        "qualifications_default": "Word・Excel基本操作できる方。コミュニケーションが得意な方。経験者優遇（未経験も応募可）。",
        "benefits_default": "交通費全額支給。有給休暇あり。産休・育休取得実績あり。社会保険完備。服装自由（スマートカジュアル）。",
        "pr_points_default": "残業少なめでワークライフバランスを重視。チームで協力しながら働ける職場です。スキルアップ研修制度あり。",
    },
    "engineer": {
        "name": "ITエンジニア",
        "qualifications_default": "プログラミング経験1年以上（言語不問）。自発的に学ぶ意欲のある方。チームで開発経験がある方。",
        "benefits_default": "リモートワーク可（週2〜3日）。書籍・勉強会費用補助。フレックスタイム制。社会保険完備。",
        "pr_points_default": "最新技術スタックを使ったプロダクト開発に携われます。副業OK。技術カンファレンス参加支援あり。",
    },
    "retail": {
        "name": "販売員・レジスタッフ",
        "qualifications_default": "接客経験歓迎（未経験可）。土日祝出勤できる方。明るく元気に接客できる方。",
        "benefits_default": "社員割引あり。交通費支給（規定内）。シフト制・週2日〜OK。社会保険完備（週30h以上）。",
        "pr_points_default": "人気ブランドの商品知識が身につきます。接客スキルを磨ける研修制度あり。昇給・正社員登用制度あり。",
    },
    "driver": {
        "name": "配送ドライバー",
        "qualifications_default": "普通自動車免許必須（AT限定可）。大型・中型免許保持者優遇。体力に自信のある方。",
        "benefits_default": "マイカー通勤可（駐車場完備）。各種手当あり（皆勤手当・早出手当等）。社会保険完備。",
        "pr_points_default": "ルート配送中心で仕事を覚えやすい環境です。デジタコ・カーナビ完備の新型車両。残業少なめです。",
    },
    "medical": {
        "name": "医療事務・クリニックスタッフ",
        "qualifications_default": "医療事務の資格歓迎（未経験可）。Word・Excel基本操作できる方。患者様に丁寧に接することができる方。",
        "benefits_default": "医療事務資格取得支援。制服貸与。交通費支給。社会保険完備。産休・育休取得実績あり。",
        "pr_points_default": "未経験からでも丁寧に指導します。地域のかかりつけ医として安定した職場環境です。土日休みで働きやすい。",
    },
    "other": {
        "name": "その他",
        "qualifications_default": "",
        "benefits_default": "",
        "pr_points_default": "",
    },
}

# フォーマット別の文字数制限と指示
FORMAT_INSTRUCTIONS: dict[str, str] = {
    "indeed": (
        "【出力フォーマット: Indeed向け】\n"
        "各セクションは500字以内で記述してください。\n"
        "検索にヒットしやすいよう、職種・スキル・地名などキーワードを自然に盛り込んでください。\n"
    ),
    "townwork": (
        "【出力フォーマット: タウンワーク向け】\n"
        "全体で2000字以内に収めてください。\n"
        "読みやすい箇条書きを活用し、求職者が一目でわかる構成にしてください。\n"
    ),
    "hellowork": (
        "【出力フォーマット: ハローワーク向け】\n"
        "以下の定型ヘッダーを各セクションの前に付与してください: 「【求人情報】」\n"
        "正式な文体（です・ます調）で記述してください。\n"
        "給与・勤務時間は法的要件（最低賃金・労働基準法）に準拠した明確な記載にしてください。\n"
    ),
    "general": (
        "【出力フォーマット: 汎用】\n"
        "文字数制限はありません。詳細で魅力的な求人票を作成してください。\n"
        "求職者が応募を検討したくなるような内容を心がけてください。\n"
    ),
}

SALARY_TYPE_LABELS: dict[str, str] = {
    "hourly": "時給",
    "daily": "日給",
    "monthly": "月給",
    "annual": "年収",
}

SYSTEM_PROMPT = """\
あなたはプロの求人ライターです。
提供された情報をもとに、求職者が魅力を感じる求人票を日本語で作成してください。

以下のセクション構成で出力してください:
【仕事内容】
【応募資格】
【給与】
【勤務時間】
【待遇・福利厚生】
【会社・店舗PR】
【応募方法】

各セクションは見出し（【〇〇】）から始め、内容を続けてください。
嘘の情報は書かず、提供された情報を元に、魅力的かつ正確な表現を使ってください。
"""


async def generate_job_posting(
    industry_template: str,
    job_title: str,
    company_name: str,
    location: str,
    salary_type: str,
    salary_min: int,
    salary_max: int | None,
    work_hours: str,
    holidays: str,
    qualifications: str,
    benefits: str,
    pr_points: str,
    target_format: str,
) -> str:
    """GPT-4o-miniで求人票テキストを生成する"""
    template = INDUSTRY_TEMPLATES.get(industry_template, INDUSTRY_TEMPLATES["other"])
    industry_name = template["name"]

    salary_label = SALARY_TYPE_LABELS.get(salary_type, salary_type)
    salary_str = f"{salary_label} {salary_min:,}円"
    if salary_max:
        salary_str += f"〜{salary_max:,}円"

    format_instruction = FORMAT_INSTRUCTIONS.get(target_format, FORMAT_INSTRUCTIONS["general"])
    format_labels = {
        "indeed": "Indeed",
        "townwork": "タウンワーク",
        "hellowork": "ハローワーク",
        "general": "汎用",
    }
    format_name = format_labels.get(target_format, target_format)

    user_message = f"""{format_instruction}

以下の情報をもとに、{format_name}向けの求人票を作成してください。

【基本情報】
- 業種: {industry_name}
- 職種名: {job_title}
- 会社・店舗名: {company_name}
- 勤務地: {location}

【給与・勤務条件】
- 給与: {salary_str}
- 勤務時間: {work_hours}
- 休日・休暇: {holidays or '（記載なし）'}

【応募資格】
{qualifications or '（特記なし。未経験歓迎で記載してください）'}

【待遇・福利厚生】
{benefits or '（特記なし。一般的な内容で記載してください）'}

【アピールポイント】
{pr_points or '（特記なし。業種に合わせたアピールポイントを考えてください）'}
"""

    client = _get_client()
    resp = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        temperature=0.7,
        max_tokens=2048,
    )
    return resp.choices[0].message.content or ""


def get_template_defaults(industry_template: str) -> dict:
    """業種テンプレートのデフォルト値を返す"""
    template = INDUSTRY_TEMPLATES.get(industry_template, INDUSTRY_TEMPLATES["other"])
    return {
        "qualifications": template["qualifications_default"],
        "benefits": template["benefits_default"],
        "pr_points": template["pr_points_default"],
    }
