import os
import google.generativeai as genai
from openai import OpenAI

class LLMClient:
    def __init__(self):
        self.gemini_key = os.getenv("GEMINI_API_KEY")
        self.openai_key = os.getenv("OPENAI_API_KEY")
        self.provider = None
        
        if self.gemini_key:
            self.provider = "gemini"
            genai.configure(api_key=self.gemini_key)
            self.model = genai.GenerativeModel('gemini-2.5-flash')
        elif self.openai_key:



            self.provider = "openai"
            self.client = OpenAI(api_key=self.openai_key)
        else:
            raise ValueError("No valid LLM API Key found (GEMINI_API_KEY or OPENAI_API_KEY).")

    def generate_business_plan(self, context_text):
        if not context_text.strip():
            return "No conversation data available to analyze."

        prompt = f"""あなたはプロのビジネスコンサルタントです。
ユーザーの1日の会話ログを分析し、ビジネスの種を見つけてください。

**ユーザーの事業領域（5つ）:**
1. 電子書籍の執筆・制作・出版・プロデュース
2. マンガを使ったコンテンツ制作
3. Instagram転職系アカウント運用（@tenshoku_nocareer）
4. YouTubeでの日本史解説動画チャンネル運用
5. フリーランス（AI活用・業務自動化の開発案件）

**分析のルール:**
- 会話ログに実際に含まれる内容だけを元にアイデアを出すこと
- ログに根拠がない空想的なアイデアは書かないこと
- 各アイデアには元の会話の[HH:MM]タイムスタンプを明記すること
- 関連する事業領域を【タグ】で表示すること
- アイデアごとに実現可能性を★1〜5で評価すること

**出力形式（Markdown・日本語）:**

# 今日のビジネスインサイト（YYYY-MM-DD）

## データ概要
- 会話数: X件
- 主なトピック: ...

## 1. 発見されたアイデア
- **[HH:MM頃] [アイデア名]** 【電子書籍】★★★★☆
  - 内容: ...
  - 元の会話: 「...」（引用）
  - ネクストアクション: ...

## 2. 事業別インサイト
### 電子書籍
- ...
### Instagram / SNS
- ...
### YouTube
- ...
### フリーランス案件
- ...
（該当がない事業は「本日は該当なし」と記載）

## 3. 今日のTOP3アクション
1. ...
2. ...
3. ...

---
**分析対象ログ:**
{context_text[:15000]}
"""

        return self._call_llm(prompt)

    def extract_top_ideas(self, report_text):
        """Extract ★4+ ideas from the report as structured JSON."""
        prompt = f"""以下のビジネスインサイトレポートから、★★★★☆（4つ星）以上のアイデアを抽出してください。

**出力形式: JSON配列のみ（```json で囲まない）**
各アイデアは以下の形式:
[
  {{
    "name": "アイデア名",
    "stars": 4,
    "timestamp": "HH:MM",
    "tags": ["電子書籍", "フリーランス案件"],
    "summary": "1〜2文の要約",
    "source_quote": "元の会話の引用"
  }}
]

★4未満のアイデアは含めないこと。該当がなければ空配列 [] を返すこと。

---
{report_text}
"""
        return self._call_llm(prompt)

    def generate_proposal(self, idea, original_log):
        """Generate a detailed business proposal for a specific idea."""
        prompt = f"""あなたはプロのビジネスプランナーです。
以下のアイデアを新規事業として立ち上げるための企画書を作成してください。

**アイデア:**
- 名前: {idea['name']}
- 関連事業: {', '.join(idea['tags'])}
- 概要: {idea['summary']}
- 元の会話: {idea.get('source_quote', 'N/A')}

**企画書のフォーマット（Markdown・日本語）:**

# 事業企画書: [事業名]

## 1. エグゼクティブサマリー
（3〜5行で事業の全体像を説明）

## 2. 背景・着想の経緯
（会話ログからの着想を具体的に記述）

## 3. ターゲット顧客
- ペルソナ: ...
- 市場規模の推定: ...
- 顧客の課題/ニーズ: ...

## 4. 提供する価値（バリュープロポジション）
- ...

## 5. 収益モデル
| 収益源 | 単価 | 想定月間件数 | 月間売上 |
|--------|------|-------------|---------|
| ... | ... | ... | ... |

## 6. 競合分析
| 競合 | 強み | 弱み | 差別化ポイント |
|------|------|------|--------------|
| ... | ... | ... | ... |

## 7. MVP（最小限の実行可能プロダクト）
- 内容: ...
- 必要な期間: ...
- 必要なコスト: ...

## 8. マイルストーン（3ヶ月計画）
| 期間 | マイルストーン | 達成基準 |
|------|-------------|---------|
| 1ヶ月目 | ... | ... |
| 2ヶ月目 | ... | ... |
| 3ヶ月目 | ... | ... |

## 9. リスクと対策
| リスク | 影響度 | 対策 |
|--------|--------|------|
| ... | ... | ... |

## 10. 判定
- **推奨アクション**: 着手する / 調査を深める / 保留
- **理由**: ...

---
**参考: 元の会話ログ（抜粋）:**
{original_log[:5000]}
"""
        return self._call_llm(prompt)

    def _call_llm(self, prompt):
        """Call the configured LLM provider."""
        try:
            if self.provider == "gemini":
                response = self.model.generate_content(prompt)
                return response.text
            elif self.provider == "openai":
                response = self.client.chat.completions.create(
                    model="gpt-4o",
                    messages=[
                        {"role": "system", "content": "あなたは優秀なビジネスコンサルタントです。日本語で回答してください。"},
                        {"role": "user", "content": prompt}
                    ]
                )
                return response.choices[0].message.content
        except Exception as e:
            return f"Error generating content: {e}"

if __name__ == "__main__":
    client = LLMClient()
    print(client.generate_business_plan("Test log: I think writing a book about AI agents would be cool."))
