"""
X（Twitter）画像付き投稿スクリプト
tweepy v1 API で画像アップロード → v2 API でツイート投稿。

使い方:
  python skills/note-to-x/scripts/post_with_image.py --text "投稿文" --image path/to/image.png
  python skills/note-to-x/scripts/post_with_image.py --text "投稿文" --image path.png --dry-run
"""

import os
import sys
import argparse
import tweepy
from dotenv import load_dotenv

load_dotenv()


def get_api_v1() -> tweepy.API:
    """メディアアップロード用 v1.1 クライアント"""
    auth = tweepy.OAuth1UserHandler(
        consumer_key=os.getenv("API_KEY"),
        consumer_secret=os.getenv("API_KEY_SECRET"),
        access_token=os.getenv("ACCESS_TOKEN"),
        access_token_secret=os.getenv("ACCESS_TOKEN_SECRET"),
    )
    return tweepy.API(auth)


def get_client_v2() -> tweepy.Client:
    """ツイート投稿用 v2 クライアント"""
    return tweepy.Client(
        consumer_key=os.getenv("API_KEY"),
        consumer_secret=os.getenv("API_KEY_SECRET"),
        access_token=os.getenv("ACCESS_TOKEN"),
        access_token_secret=os.getenv("ACCESS_TOKEN_SECRET"),
    )


def post_with_image(text: str, image_path: str, dry_run: bool = False) -> dict:
    """画像付きツイートを投稿する"""

    if dry_run:
        print(f"[DRY RUN] 投稿内容（{len(text)}文字）:\n{text}")
        print(f"[DRY RUN] 添付画像: {image_path}")
        return {"id": "dry_run", "text": text}

    print("📤 画像をアップロード中...")
    api_v1 = get_api_v1()
    media = api_v1.media_upload(filename=image_path)
    media_id = media.media_id
    print(f"   ✅ media_id: {media_id}")

    print("📝 ツイートを投稿中...")
    client = get_client_v2()
    response = client.create_tweet(text=text, media_ids=[media_id])
    tweet_id = response.data["id"]

    print(f"✅ 投稿成功!")
    print(f"   ID  : {tweet_id}")
    print(f"   URL : https://x.com/i/web/status/{tweet_id}")
    return response.data


def main():
    parser = argparse.ArgumentParser(description="X 画像付き投稿")
    parser.add_argument("--text", required=True, help="投稿テキスト")
    parser.add_argument("--image", required=True, help="添付画像パス")
    parser.add_argument("--dry-run", action="store_true", help="確認のみ、投稿しない")
    args = parser.parse_args()

    post_with_image(args.text, args.image, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
