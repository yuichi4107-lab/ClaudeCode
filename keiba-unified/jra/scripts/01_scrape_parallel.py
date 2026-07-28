"""並列レーススクレイピングスクリプト

年ごとに別プロセスで並列実行し、スクレイピングを高速化する。
各プロセスは独立したレートリミッタを持ち、リクエスト間隔1.5秒で動作。
SQLite WALモードにより並列書き込みに対応。

Usage:
    python -m scripts.01_scrape_parallel
    python -m scripts.01_scrape_parallel --years 2021 2022 2023 2024 2025
    python -m scripts.01_scrape_parallel --workers 3
"""

import argparse
import os
import sys
import time
import sqlite3
from concurrent.futures import ProcessPoolExecutor, as_completed

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.database.db_manager import DBManager
from src.scraper.race_list_scraper import scrape_race_ids_for_year
from src.scraper.race_result_scraper import scrape_race
from src.utils.config_loader import get_db_path, load_settings
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


def _get_scraped_ids(db_path: str) -> set:
    """完了済みレースIDを取得（プロセス安全）"""
    conn = sqlite3.connect(db_path, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    cur = conn.execute("SELECT race_id FROM scrape_log WHERE status = 'done'")
    ids = {row[0] for row in cur.fetchall()}
    conn.close()
    return ids


def _scrape_single_race(race_id: str, db_path: str) -> str:
    """1レースをスクレイピングしてDBに保存する"""
    db = DBManager(db_path)
    try:
        data = scrape_race(race_id)
        if data is None:
            db.update_scrape_log(race_id, "error", "Failed to fetch page")
            return "error"

        db.insert_race(data["race_info"])
        db.insert_race_results_batch(data["results"])
        db.insert_payoffs_batch(data["payoffs"])
        db.update_scrape_log(race_id, "done")
        return "ok"
    except sqlite3.OperationalError as e:
        if "locked" in str(e).lower():
            # DB locked -> retry once after short wait
            time.sleep(0.5)
            try:
                db.insert_race(data["race_info"])
                db.insert_race_results_batch(data["results"])
                db.insert_payoffs_batch(data["payoffs"])
                db.update_scrape_log(race_id, "done")
                return "ok"
            except Exception:
                db.update_scrape_log(race_id, "error", str(e))
                return "error"
        db.update_scrape_log(race_id, "error", str(e))
        return "error"
    except Exception as e:
        try:
            db.update_scrape_log(race_id, "error", str(e))
        except Exception:
            pass
        return "error"


def scrape_year(year: int, db_path: str, interval: float = 1.5) -> dict:
    """1年分のレースを順次スクレイピングする（各プロセスで実行）"""
    import src.scraper.scraper_utils as su
    # プロセスごとにリクエスト間隔を設定
    su._scraping_cfg = {**su._scraping_cfg, "request_interval_sec": interval}

    logger.info("[Year %d] Starting scrape", year)

    # レースID取得
    race_ids = scrape_race_ids_for_year(year)
    logger.info("[Year %d] Found %d race IDs", year, len(race_ids))

    # 完了済みを除外
    scraped = _get_scraped_ids(db_path)
    remaining = [rid for rid in race_ids if rid not in scraped]
    logger.info("[Year %d] %d remaining (skipped %d)", year, len(remaining), len(race_ids) - len(remaining))

    ok = 0
    err = 0
    for i, race_id in enumerate(remaining):
        result = _scrape_single_race(race_id, db_path)
        if result == "ok":
            ok += 1
        else:
            err += 1
        if (i + 1) % 100 == 0:
            logger.info("[Year %d] Progress: %d/%d (ok=%d, err=%d)", year, i + 1, len(remaining), ok, err)

    logger.info("[Year %d] Complete: ok=%d, err=%d, total=%d", year, ok, err, len(remaining))
    return {"year": year, "ok": ok, "err": err, "total": len(remaining)}


def main():
    parser = argparse.ArgumentParser(description="Parallel race scraper")
    parser.add_argument("--years", nargs="+", type=int, default=None)
    parser.add_argument("--workers", type=int, default=5)
    parser.add_argument("--interval", type=float, default=1.5,
                        help="Request interval per worker in seconds")
    parser.add_argument("--db-path", type=str, default=None)
    args = parser.parse_args()

    settings = load_settings()
    db_path = args.db_path or get_db_path()
    years = args.years or settings["scraping"]["years"]

    # DB初期化（WAL + busy_timeout）
    db = DBManager(db_path)
    db.init_db()

    # busy_timeout設定（並列書き込み対策）
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.close()

    logger.info("Starting parallel scrape: years=%s, workers=%d, interval=%.1fs", years, args.workers, args.interval)

    start_time = time.time()

    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(scrape_year, year, db_path, args.interval): year
            for year in years
        }
        results = {}
        for future in as_completed(futures):
            year = futures[future]
            try:
                result = future.result()
                results[year] = result
                logger.info("Year %d finished: %s", year, result)
            except Exception as e:
                logger.error("Year %d failed: %s", year, e)
                results[year] = {"year": year, "ok": 0, "err": 0, "error": str(e)}

    elapsed = time.time() - start_time
    total_ok = sum(r.get("ok", 0) for r in results.values())
    total_err = sum(r.get("err", 0) for r in results.values())

    logger.info("=" * 60)
    logger.info("All scraping complete in %.0f seconds (%.1f minutes)", elapsed, elapsed / 60)
    logger.info("Total: ok=%d, errors=%d", total_ok, total_err)
    for year in sorted(results.keys()):
        logger.info("  %d: %s", year, results[year])
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
