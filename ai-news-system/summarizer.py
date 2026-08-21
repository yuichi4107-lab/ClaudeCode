"""生成部: Gemini API でAIニュースを要約・翻訳する"""

import json
import logging
import os

from google import genai

logger = logging.getLogger(__name__)

SUMMARY_PROMPT_TEMPLATE = """\
あなたはAI業界の専門ニュースキュレーターです。
以下の{count}件の英語ツイート（AI関連）を日本語のニュースダイジェストにまとめてください。

【ルール】
1. 各ニュースは「タイトル」「本文（2-3文の要約）」「ソースURL」の形式で出力
2. 重複する話題は1つにまともる
3. 広告・スパユ・無関係なツイートは無視する
4. 重要度の高いニュースを上位に配置する
5. 専門用語は必要に応じて簡潔に補足する
6. 最大10件のニュースにまともる

【出力フォーマット】
📰 AIニュースダイジェスト（{date}）

■ ニュースタイトル1
本文要約（2-3文）
🔗 ソースURL

■ ニュースタイトル2
...

【ツイートデータ】
{tweets}
"""


def summarize_tweets(tweets: list[dict], date_str: str = "") -> str:
    """ツイート群をClaude Code CLIで要約・翻訳する

    Args:
        tweets: collector.pyで取得したツイートのリスト
        date_str: 配信日付文字列（例: "2026年4月1日"）

    Returns:
        日本語のニュースダイジェスト文字列
    """
    if not tweets:
        logger.warning("要約対象のツイートがありません")
        return ""

    # ツイートをテキストにまとめる
    tweet_texts = []
    for i, tweet in enumerate(tweets, 1):
        tweet_texts.append(
            f"[{i}] {tweet['text']}\n"
            f"    URL: {tweet['url']}\n"
            f"    Date: {tweet.get('created_at', 'N/A')}"
        )
    input_text = "\n\n".join(tweet_texts)

    prompt = SUMMARY_PROMPT_TEMPLATE.format(
        count=len(tweets),
        date=date_str or "本日",
        tweets=input_text,
    )

    try:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            logger.error("GEMINI_API_KEY が設定されていません")
            return ""

        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        digest = response.text.strip()
        logger.info(f"[OK] ニュースダイジェストを生成しました（{len(digest)}文字）")
        return digest

    except Exception as e:
        logger.error(f"Gemini API エラー: {e}")
        return ""


def save_tweets_json(tweets: list[dict], path: str = "tweets.json") -> str:
    """収集したツイートをJSONファイルに保存する"""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(tweets, f, ensure_ascii=False, indent=2)
    logger.info(f"[OK] ツイートデータを保存: {path}")
    return path


def load_tweets_json(path: str = "tweets.json") -> list[dict]:
    """保存済みツイートJSONを読み込む"""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # テスト用サンプルデータ
    sample_tweets = [
        {
            "text": "OpenAI just released GPT-5 with breakthrough reasoning capabilities. "
                    "Early benchmarks show 40% improvement over GPT-4 on complex tasks.",
            "url": "https://twitter.com/i/web/status/123456",
            "created_at": "2026-04-01T06:00:00Z",
        },
        {
            "text": "Google DeepMind announces Gemini 2.5 Ultra with native multimodal understanding. "
                    "Can process video, audio, and code simultaneously.",
            "url": "https://twitter.com/i/web/status/789012",
            "created_at": "2026-04-01T05:30:00Z",
        },
    ]
    result = summarize_tweets(sample_tweets, "2026年4月1日")
    print(result)
