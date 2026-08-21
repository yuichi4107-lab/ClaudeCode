"""開催日のレース結果を収集して既存データに追加するスクリプト

開催日の22時にcronで実行し、当日のレース結果を
data/raw/race_results.csv に追記する。

使い方:
    PYTHONPATH=. python3 scripts/collect_results.py
    PYTHONPATH=. python3 scripts/collect_results.py --date 2026-03-14
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime

import pandas as pd

from config.settings import RAW_DATA_DIR
from src.scraper.banei_scraper import BaneiScraper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def collect_and_append(target_date: date) -> bool:
    """当日のレース結果を取得してCSVに追記する"""
    raw_file = RAW_DATA_DIR / "race_results.csv"

    # 既存データを読み込み、当日のデータが既にあるかチェック
    if raw_file.exists():
        existing = pd.read_csv(raw_file)
        date_str = target_date.strftime("%Y-%m-%d")
        if date_str in existing["race_date"].values:
            logger.info("%s のデータは既に登録済みです（%d件）",
                        date_str,
                        len(existing[existing["race_date"] == date_str]))
            return False
    else:
        existing = pd.DataFrame()

    # 当日のレース結果をスクレイピング
    logger.info("%s のレース結果を取得中...", target_date)
    scraper = BaneiScraper()
    df = scraper.scrape_date_range(target_date, target_date)

    if df.empty:
        logger.info("%s は開催がありません", target_date)
        return False

    # 既存データに追記
    if not existing.empty:
        combined = pd.concat([existing, df], ignore_index=True)
    else:
        combined = df

    RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
    combined.to_csv(raw_file, index=False, encoding="utf-8-sig")

    logger.info("結果追加完了: %s (%d件追加, 合計%d件)",
                target_date, len(df), len(combined))
    return True


def main():
    parser = argparse.ArgumentParser(description="帯広ばんえい競馬 レース結果収集")
    parser.add_argument("--date", help="収集日 (YYYY-MM-DD, デフォルト: 本日)")
    args = parser.parse_args()

    if args.date:
        target_date = datetime.strptime(args.date, "%Y-%m-%d").date()
    else:
        target_date = date.today()

    collect_and_append(target_date)


if __name__ == "__main__":
    main()
