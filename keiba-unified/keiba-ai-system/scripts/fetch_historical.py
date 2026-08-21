"""過去データ一括取得スクリプト

指定期間のばんえい競馬データをスクレイピングし、
既存のrace_results.csvにマージ保存する。

使い方:
    PYTHONPATH=. python scripts/fetch_historical.py --start 2021-04-01 --end 2025-08-31
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, ".")

from config.settings import RAW_DATA_DIR
from src.scraper.banei_scraper import BaneiScraper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

RAW_FILE = RAW_DATA_DIR / "race_results.csv"


def fetch_month(scraper: BaneiScraper, year: int, month: int) -> pd.DataFrame:
    """1ヶ月分のデータを取得"""
    start = date(year, month, 1)
    if month == 12:
        end = date(year, 12, 31)
    else:
        end = date(year, month + 1, 1) - timedelta(days=1)

    logger.info("取得中: %d/%02d (%s ~ %s)", year, month, start, end)
    df = scraper.scrape_date_range(start, end, use_entries=False)
    if not df.empty:
        logger.info("  → %d頭分取得", len(df))
    else:
        logger.info("  → データなし")
    return df


def main():
    parser = argparse.ArgumentParser(description="ばんえい過去データ一括取得")
    parser.add_argument("--start", required=True, help="開始日 (YYYY-MM-DD)")
    parser.add_argument("--end", required=True, help="終了日 (YYYY-MM-DD)")
    args = parser.parse_args()

    start = datetime.strptime(args.start, "%Y-%m-%d").date()
    end = datetime.strptime(args.end, "%Y-%m-%d").date()

    # 既存データ読み込み
    if RAW_FILE.exists():
        existing = pd.read_csv(RAW_FILE)
        logger.info("既存データ: %d行 (%s ~ %s)", len(existing),
                     existing["race_date"].min(), existing["race_date"].max())
    else:
        existing = pd.DataFrame()
        logger.info("既存データなし")

    scraper = BaneiScraper()
    all_new = []

    # 月単位でループ（途中保存あり）
    current = date(start.year, start.month, 1)
    while current <= end:
        yr, mo = current.year, current.month
        df = fetch_month(scraper, yr, mo)
        if not df.empty:
            all_new.append(df)

        # 3ヶ月ごとに中間保存
        if len(all_new) > 0 and (mo % 3 == 0 or current.month == end.month and current.year == end.year):
            new_df = pd.concat(all_new, ignore_index=True)
            merged = pd.concat([existing, new_df], ignore_index=True)
            merged = merged.drop_duplicates(
                subset=["race_date", "race_no", "horse_number"], keep="last"
            )
            merged = merged.sort_values(["race_date", "race_no", "horse_number"])
            merged.to_csv(RAW_FILE, index=False, encoding="utf-8-sig")
            logger.info("中間保存: %d行 (既存+新規マージ済み)", len(merged))
            existing = merged
            all_new = []

        # 次の月へ
        if mo == 12:
            current = date(yr + 1, 1, 1)
        else:
            current = date(yr, mo + 1, 1)

    # 最終保存
    if all_new:
        new_df = pd.concat(all_new, ignore_index=True)
        merged = pd.concat([existing, new_df], ignore_index=True)
        merged = merged.drop_duplicates(
            subset=["race_date", "race_no", "horse_number"], keep="last"
        )
        merged = merged.sort_values(["race_date", "race_no", "horse_number"])
        merged.to_csv(RAW_FILE, index=False, encoding="utf-8-sig")
        logger.info("最終保存: %d行", len(merged))

    # 結果サマリ
    final = pd.read_csv(RAW_FILE)
    logger.info("=== 完了 ===")
    logger.info("全データ: %d行", len(final))
    logger.info("期間: %s ~ %s", final["race_date"].min(), final["race_date"].max())


if __name__ == "__main__":
    main()
