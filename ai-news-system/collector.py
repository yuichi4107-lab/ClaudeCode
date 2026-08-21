"""収集部: X API (Twitter API v2) でAI関連ツイートを取得"""

import os
import logging
from datetime import datetime, timedelta, timezone

import requests

logger = logging.getLogger(__name__)

# 検索キーワード
SEARCH_KEYWORDS = [
    "AI", "LLM", "GPT", "Claude", "Gemini", "機械学習",
    "OpenAI", "Anthropic", "Google DeepMind", "machine learning",
]

def build_search_query() -> str:
    """検索クエリを構築する"""
    keywords = " OR ".join(SEARCH_KEYWORDS)
    return f'({keywords}) lang:en -is:retweet -is:reply -"crypto" -"airdrop" -"giveaway"'


def fetch_tweets(max_results: int = 50) -> list[dict]:
    """X API v2 で最新ツイートを検索・取得する

    Returns:
        list[dict]: ツイートのリスト。各要素は {id, text, author_id, created_at, url} を含む。
    """
    bearer_token = os.getenv("TWITTER_BEARER_TOKEN")
    if not bearer_token:
        logger.error("TWITTER_BEARER_TOKEN が設定されていません")
        return []

    url = "https://api.twitter.com/2/tweets/search/recent"
    headers = {"Authorization": f"Bearer {bearer_token}"}

    # 過去24時間のツイートを取得
    start_time = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    params = {
        "query": build_search_query(),
        "max_results": min(max_results, 100),  # API上限は100
        "start_time": start_time,
        "tweet.fields": "created_at,author_id,public_metrics",
        "sort_order": "relevancy",
    }

    try:
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        tweets = []
        for tweet in data.get("data", []):
            tweets.append({
                "id": tweet["id"],
                "text": tweet["text"],
                "author_id": tweet.get("author_id", ""),
                "created_at": tweet.get("created_at", ""),
                "url": f"https://twitter.com/i/web/status/{tweet['id']}",
                "metrics": tweet.get("public_metrics", {}),
            })

        logger.info(f"[OK] {len(tweets)}件のツイートを取得しました")
        return tweets

    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 429:
            logger.warning("X API レート制限に達しました。時間をおいて再実行してください。")
        else:
            logger.error(f"X API エラー: {e}")
        return []
    except requests.exceptions.RequestException as e:
        logger.error(f"ネットワークエラー: {e}")
        return []


def filter_by_engagement(tweets: list[dict], min_likes: int = 5) -> list[dict]:
    """エンゲージメントが低すぎるツイートを除外する"""
    filtered = []
    for tweet in tweets:
        metrics = tweet.get("metrics", {})
        likes = metrics.get("like_count", 0)
        retweets = metrics.get("retweet_count", 0)
        if likes >= min_likes or retweets >= 2:
            filtered.append(tweet)
    logger.info(f"[OK] エンゲージメントフィルタ: {len(tweets)}件 → {len(filtered)}件")
    return filtered


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    logging.basicConfig(level=logging.INFO)

    tweets = fetch_tweets(max_results=30)
    tweets = filter_by_engagement(tweets)
    for t in tweets[:5]:
        print(f"[{t['created_at']}] {t['text'][:80]}...")
        print(f"  URL: {t['url']}")
        print()
