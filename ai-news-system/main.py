"""AIニュース配信システム - メインパイプライン

収集 → 要約・翻訳 → 配信 を一括実行するエントリーポイント。
cron等で毎朝定時実行することを想定。
"""

import os
import sys
import logging
from datetime import datetime

from dotenv import load_dotenv

from collector import fetch_tweets, filter_by_engagement
from summarizer import summarize_tweets
from distributor import send_line_message, post_to_x, save_to_google_docs, save_to_local

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("ai_news.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


def run_pipeline():
    """ニュース配信パイプラインを実行する"""
    logger.info("=" * 60)
    logger.info("AIニュース配信パイプライン 開始")
    logger.info("=" * 60)

    today = datetime.now().strftime("%Y年%m月%d日")

    # ===== Step 1: 収集 =====
    logger.info("[Step 1] AI関連ツイートを収集中...")
    tweets = fetch_tweets(max_results=50)

    if not tweets:
        logger.warning("ツイートが取得できませんでした。処理を終了します。")
        return

    # エンゲージメントフィルタ
    tweets = filter_by_engagement(tweets, min_likes=5)

    if not tweets:
        logger.warning("フィルタ後のツイートが0件です。処理を終了します。")
        return

    logger.info(f"[Step 1] 完了: {len(tweets)}件のツイートを収集")

    # ===== Step 2: 要約・翻訳 =====
    logger.info("[Step 2] Claude Code CLIで要約・翻訳中...")
    digest = summarize_tweets(tweets, date_str=today)

    if not digest:
        logger.error("ニュースダイジェストの生成に失敗しました。")
        return

    logger.info(f"[Step 2] 完了: {len(digest)}文字のダイジェストを生成")

    # ===== Step 3: 配信 =====
    logger.info("[Step 3] ニュースを配信中...")

    # 3-1. ローカル保存（必ず実行）
    local_path = save_to_local(digest, output_dir="output")
    logger.info(f"  ローカル保存: {local_path}")

    # 3-2. LINE Messaging API（トークンがあれば実行）
    if os.getenv("LINE_CHANNEL_ACCESS_TOKEN"):
        send_line_message(digest)
    else:
        logger.info("  LINE: チャネルアクセストークン未設定 - スキップ")

    # 3-3. X (Twitter) 投稿（認証情報があれば実行）
    if os.getenv("X_API_KEY"):
        post_to_x(digest)
    else:
        logger.info("  X: API認証未設定 - スキップ")

    # 3-4. Google Docs（GAS Webアプリ設定があれば実行）
    if os.getenv("GAS_WEBAPP_URL"):
        doc_title = f"AIニュースダイジェスト_{datetime.now().strftime('%Y%m%d')}"
        doc_url = save_to_google_docs(digest, title=doc_title)
        if doc_url:
            logger.info(f"  Google Docs: {doc_url}")
    else:
        logger.info("  Google Docs: GAS_WEBAPP_URL 未設定 - スキップ")

    logger.info("=" * 60)
    logger.info("AIニュース配信パイプライン 完了")
    logger.info("=" * 60)


if __name__ == "__main__":
    load_dotenv()
    run_pipeline()
