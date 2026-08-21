"""レーススクレイピングメインスクリプト

Usage:
    python -m scripts.01_scrape_races --years 2021 2022 2023 2024 2025
    python -m scripts.01_scrape_races --years 2024 --resume
"""

import argparse
import sys
import os

# プロジェクトルートをPATHに追加
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tqdm import tqdm

from src.database.db_manager import DBManager
from src.scraper.race_list_scraper import scrape_race_ids_for_years
from src.scraper.race_result_scraper import scrape_race
from src.utils.config_loader import get_db_path, load_settings
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


def parse_args():
    parser = argparse.ArgumentParser(
        description="JRA race data scraper for netkeiba.com"
    )
    parser.add_argument(
        "--years",
        nargs="+",
        type=int,
        default=None,
        help="Years to scrape (default: from settings.yaml)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        default=True,
        help="Skip already scraped races (default: True)",
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default=None,
        help="Database path (default: from settings.yaml)",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    settings = load_settings()

    db_path = args.db_path or get_db_path()
    years = args.years or settings["scraping"]["years"]

    logger.info("Starting scraper for years: %s", years)
    logger.info("Database path: %s", db_path)

    # DB初期化
    db = DBManager(db_path)
    db.init_db()

    # 完了済みレースID取得
    scraped_ids = db.get_scraped_race_ids() if args.resume else set()
    logger.info("Already scraped: %d races", len(scraped_ids))

    # レースID一覧取得
    logger.info("Collecting race IDs...")
    all_race_ids = scrape_race_ids_for_years(years)
    logger.info("Total race IDs found: %d", len(all_race_ids))

    # 未スクレイピングのレースをフィルタ
    remaining = [rid for rid in all_race_ids if rid not in scraped_ids]
    logger.info("Races to scrape: %d (skipped %d)", len(remaining), len(all_race_ids) - len(remaining))

    # スクレイピング実行
    success_count = 0
    error_count = 0

    for race_id in tqdm(remaining, desc="Scraping races"):
        try:
            data = scrape_race(race_id)
            if data is None:
                db.update_scrape_log(race_id, "error", "Failed to fetch page")
                error_count += 1
                continue

            # DB保存
            db.insert_race(data["race_info"])
            db.insert_race_results_batch(data["results"])
            db.insert_payoffs_batch(data["payoffs"])
            db.update_scrape_log(race_id, "done")
            success_count += 1

        except Exception as e:
            logger.error("Error scraping %s: %s", race_id, e)
            db.update_scrape_log(race_id, "error", str(e))
            error_count += 1

    logger.info(
        "Scraping complete. Success: %d, Errors: %d, Total: %d",
        success_count, error_count, len(remaining),
    )


if __name__ == "__main__":
    main()
