"""配信部: LINE Messaging API + X(Twitter) + Google Docs でニュースを配信する"""

import os
import json
import logging
from datetime import datetime

import re

import requests
from requests_oauthlib import OAuth1

logger = logging.getLogger(__name__)


# =============================================================================
# LINE Messaging API 配信
# =============================================================================

def send_line_message(message: str) -> bool:
    """LINE Messaging API でメッセージを送信する

    Args:
        message: 送信するメッセージ（最大5000文字）

    Returns:
        送信成功ならTrue
    """
    token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
    user_id = os.getenv("LINE_USER_ID")

    if not token:
        logger.error("LINE_CHANNEL_ACCESS_TOKEN が設定されていません")
        return False
    if not user_id:
        logger.error("LINE_USER_ID が設定されていません")
        return False

    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    # Messaging APIは1メッセージ5000文字制限、1リクエスト5バブルまで
    chunks = _split_message(message, max_length=5000)

    success = True
    for i, chunk in enumerate(chunks):
        body = {
            "to": user_id,
            "messages": [{"type": "text", "text": chunk}],
        }
        try:
            resp = requests.post(url, headers=headers, json=body, timeout=15)
            resp.raise_for_status()
            logger.info(f"[OK] LINE 送信完了 ({i+1}/{len(chunks)})")
        except requests.exceptions.RequestException as e:
            logger.error(f"LINE 送信エラー: {e}")
            if hasattr(e, "response") and e.response is not None:
                logger.error(f"  詳細: {e.response.text}")
            success = False

    return success


def _split_message(message: str, max_length: int = 1000) -> list[str]:
    """メッセージを指定文字数以内に分割する"""
    if len(message) <= max_length:
        return [message]

    chunks = []
    lines = message.split("\n")
    current_chunk = ""

    for line in lines:
        # 1行がmax_lengthを超える場合は強制分割
        while len(line) > max_length:
            if current_chunk:
                chunks.append(current_chunk)
                current_chunk = ""
            chunks.append(line[:max_length])
            line = line[max_length:]

        if len(current_chunk) + len(line) + 1 > max_length:
            if current_chunk:
                chunks.append(current_chunk)
            current_chunk = line
        else:
            current_chunk = f"{current_chunk}\n{line}" if current_chunk else line

    if current_chunk:
        chunks.append(current_chunk)

    return chunks


# =============================================================================
# X (Twitter) 投稿
# =============================================================================

def _strip_emoji(text: str) -> str:
    """絵文字を除去する（X API 403対策）"""
    return re.sub(
        r'[\U0001F300-\U0001FAFF\U00002702-\U000027B0\U0000FE00-\U0000FE0F\U0000200D]',
        '', text
    ).strip()


def _weighted_len(text: str) -> int:
    """X APIのウェイト付き文字数を計算する（日本語=2, ASCII=1）"""
    count = 0
    for ch in text:
        count += 1 if ord(ch) < 128 else 2
    return count


def _make_x_summary(digest: str, max_weight: int = 280) -> str:
    """ダイジェストからX投稿用の短縮テキストを生成する"""
    lines = digest.strip().split("\n")
    topics = []
    for line in lines:
        if line.startswith("■"):
            topic = _strip_emoji(line.replace("■ ", "").replace("■", ""))
            if topic:
                topics.append("・" + topic)

    if not topics:
        return _strip_emoji(digest)[:140]

    footer = "\n\n#AIニュース #AI #LLM"
    body = "AIニュースダイジェスト\n\n"

    for topic in topics:
        candidate = body + topic + "\n"
        if _weighted_len(candidate + footer) > max_weight:
            break
        body = candidate

    result = body.rstrip() + footer
    # 最終安全チェック
    while _weighted_len(result) > max_weight and "\n・" in result:
        result = result[:result.rfind("\n・")] + footer
    return result


def post_to_x(digest: str) -> bool:
    """X (Twitter) にAIニュースダイジェストの要約を投稿する

    Args:
        digest: 全文ダイジェスト（280文字に短縮して投稿）

    Returns:
        投稿成功ならTrue
    """
    api_key = os.getenv("X_API_KEY")
    api_secret = os.getenv("X_API_KEY_SECRET")
    access_token = os.getenv("X_ACCESS_TOKEN")
    access_secret = os.getenv("X_ACCESS_TOKEN_SECRET")

    if not all([api_key, api_secret, access_token, access_secret]):
        logger.warning("X API認証情報が不足しています - スキップ")
        return False

    auth = OAuth1(api_key, api_secret, access_token, access_secret)
    tweet_text = _make_x_summary(digest)

    try:
        resp = requests.post(
            "https://api.twitter.com/2/tweets",
            json={"text": tweet_text},
            auth=auth,
            timeout=15,
        )
        resp.raise_for_status()
        tweet_id = resp.json().get("data", {}).get("id", "")
        logger.info(f"[OK] X投稿完了: https://twitter.com/i/web/status/{tweet_id}")
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"X投稿エラー: {e}")
        if hasattr(e, "response") and e.response is not None:
            logger.error(f"  詳細: {e.response.text}")
        return False


# =============================================================================
# Google Docs アーカイブ
# =============================================================================

def save_to_google_docs(content: str, title: str = "") -> str | None:
    """Google Docsにニュースアーカイブを保存する（GAS Webアプリ経由）

    Args:
        content: 保存するニュース本文
        title: ドキュメントタイトル

    Returns:
        作成したドキュメントのURLまたはNone
    """
    webapp_url = os.getenv("GAS_WEBAPP_URL")
    auth_token = os.getenv("GAS_AUTH_TOKEN")

    if not webapp_url:
        logger.warning("GAS_WEBAPP_URL 未設定 - Google Docs保存をスキップ")
        return None
    if not auth_token:
        logger.warning("GAS_AUTH_TOKEN 未設定 - Google Docs保存をスキップ")
        return None

    if not title:
        title = f"AIニュースダイジェスト_{datetime.now().strftime('%Y%m%d')}"

    payload = {
        "token": auth_token,
        "content": content,
        "title": title,
        "date": datetime.now().strftime("%Y-%m-%d"),
    }

    # GAS Webアプリは302リダイレクトを返すことがある。
    # requests.postはデフォルトでリダイレクトに追従するが、POST→GETに変わる場合がある。
    # その場合は allow_redirects=False にして Location ヘッダを手動で処理する。
    max_retries = 2
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.post(
                webapp_url,
                json=payload,
                timeout=30,
            )
            resp.raise_for_status()

            result = resp.json()
            if result.get("success"):
                doc_url = result["url"]
                logger.info(f"[OK] Google Docs に保存しました: {doc_url}")
                return doc_url
            else:
                error_msg = result.get("error", "不明なエラー")
                logger.error(f"Google Docs 保存エラー (GAS): {error_msg}")
                return None

        except requests.exceptions.Timeout:
            logger.warning(f"Google Docs 保存タイムアウト (試行 {attempt}/{max_retries})")
            if attempt >= max_retries:
                logger.error("Google Docs 保存: タイムアウトによりリトライ上限に到達")
                return None
        except requests.exceptions.RequestException as e:
            logger.error(f"Google Docs 保存エラー: {e}")
            return None
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"Google Docs レスポンス解析エラー: {e}")
            return None

    return None


# =============================================================================
# ローカルファイル保存（フォールバック）
# =============================================================================

def save_to_local(content: str, output_dir: str = "output") -> str:
    """ローカルファイルにニュースを保存する（フォールバック）"""
    os.makedirs(output_dir, exist_ok=True)
    filename = f"ai_news_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    filepath = os.path.join(output_dir, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

    logger.info(f"[OK] ローカル保存: {filepath}")
    return filepath


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    logging.basicConfig(level=logging.INFO)

    test_message = "📰 テスト配信\n\n■ テストニュース\nこれはテストメッセージです。"

    # LINE Messaging API テスト
    if os.getenv("LINE_CHANNEL_ACCESS_TOKEN"):
        send_line_message(test_message)
    else:
        print("LINE_CHANNEL_ACCESS_TOKEN 未設定 - スキップ")

    # Google Docs 保存テスト
    if os.getenv("GAS_WEBAPP_URL"):
        doc_url = save_to_google_docs(test_message, title="テスト配信")
        print(f"Google Docs: {doc_url}")
    else:
        print("GAS_WEBAPP_URL 未設定 - スキップ")

    # ローカル保存テスト
    path = save_to_local(test_message)
    print(f"ローカル保存: {path}")
