"""
X（Twitter）投稿スクリプト
Phase 0: 開通テスト用

使い方:
  python skills/note-to-x/scripts/post_to_x.py
  python skills/note-to-x/scripts/post_to_x.py --text "投稿内容"
"""

import os
import sys
import argparse
import time
import tweepy
from dotenv import load_dotenv

load_dotenv()


def get_client() -> tweepy.Client:
    """X API クライアントを初期化する"""
    required = ["API_KEY", "API_KEY_SECRET", "ACCESS_TOKEN", "ACCESS_TOKEN_SECRET"]
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        raise EnvironmentError(
            f"以下の環境変数が設定されていません: {', '.join(missing)}\n"
            ".env.example をコピーして .env を作成し、キーを入力してください。"
        )

    return tweepy.Client(
        consumer_key=os.getenv("API_KEY"),
        consumer_secret=os.getenv("API_KEY_SECRET"),
        access_token=os.getenv("ACCESS_TOKEN"),
        access_token_secret=os.getenv("ACCESS_TOKEN_SECRET"),
    )


def post_tweet(text: str, dry_run: bool = False) -> dict:
    """ツイートを投稿する。dry_run=True の場合は投稿せず確認のみ。"""
    if len(text) > 280:
        raise ValueError(f"文字数オーバー: {len(text)}文字（上限280文字）")

    if dry_run:
        print(f"[DRY RUN] 投稿内容（{len(text)}文字）:\n{text}")
        return {"id": "dry_run", "text": text}

    client = get_client()

    for attempt in range(3):
        try:
            response = client.create_tweet(text=text)
            tweet_id = response.data["id"]
            print(f"✅ 投稿成功!")
            print(f"   ID  : {tweet_id}")
            print(f"   URL : https://x.com/i/web/status/{tweet_id}")
            print(f"   本文: {text}")
            return response.data
        except tweepy.errors.TooManyRequests:
            wait = 60 * (2 ** attempt)
            print(f"⚠️  レート制限。{wait}秒後にリトライ... ({attempt+1}/3)")
            time.sleep(wait)
        except tweepy.errors.Forbidden as e:
            print("❌ 権限エラー（403）")
            print("   原因: App Permissionsが「Read」のみになっている可能性があります。")
            print("   対処: Developer Portal > App Settings > User authentication settings")
            print("         > App permissions を「Read and Write」に変更後、")
            print("         Access Token を再生成してください。")
            raise
        except tweepy.errors.Unauthorized as e:
            print("❌ 認証エラー（401）")
            print("   原因: APIキーまたはトークンが正しくありません。")
            print("   対処: .env の API_KEY / ACCESS_TOKEN を確認してください。")
            raise

    raise RuntimeError("最大リトライ回数を超えました。")


def main():
    parser = argparse.ArgumentParser(description="X投稿テスト")
    parser.add_argument("--text", default=None, help="投稿内容（省略時はテスト文）")
    parser.add_argument("--dry-run", action="store_true", help="投稿せずに確認のみ")
    args = parser.parse_args()

    text = args.text or "X-skill 開通テスト ✅ note→X自動投稿スキルを開発中です！"

    print(f"投稿内容（{len(text)}文字）:\n{text}\n")

    if not args.dry_run:
        confirm = input("この内容で投稿しますか？ [y/N]: ").strip().lower()
        if confirm != "y":
            print("キャンセルしました。")
            sys.exit(0)

    post_tweet(text, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
