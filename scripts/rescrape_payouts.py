"""Rescrape payouts for races that have no payouts recorded.

This script finds races with missing payouts and invokes RaceResultScraper.scrape
to parse payouts and save them via Repository.upsert_payout.
"""
from nankan_predictor.storage.repository import Repository
from nankan_predictor.scraper.race_result import RaceResultScraper
from nankan_predictor.config.settings import DB_PATH
import sqlite3
import time

RETRY_SLEEP = 1.0
BATCH_LIMIT = 200


def find_races_missing_payouts(conn, limit=BATCH_LIMIT):
    cur = conn.cursor()
    sql = """
    SELECT r.race_id
    FROM races r
    LEFT JOIN race_payouts rp ON r.race_id = rp.race_id
    WHERE rp.race_id IS NULL
    ORDER BY r.race_date DESC
    LIMIT ?
    """
    cur.execute(sql, (limit,))
    return [r[0] for r in cur.fetchall()]


def main():
    repo = Repository()
    conn = repo._conn()
    scraper = RaceResultScraper()

    races = find_races_missing_payouts(conn)
    print(f"Found {len(races)} races missing payouts (lim={BATCH_LIMIT})")
    for i, race_id in enumerate(races, 1):
        try:
            print(f"[{i}/{len(races)}] Scraping payouts for {race_id}")
            data = scraper.scrape(race_id)
            payouts = data.get("payouts", [])
            if not payouts:
                print(f"  No payouts parsed for {race_id}")
            for p in payouts:
                repo.upsert_payout(p["race_id"], p["bet_type"], p["combination"], p["payout"])
            # be gentle with remote
            time.sleep(RETRY_SLEEP)
        except Exception as e:
            print(f"  Error scraping {race_id}: {e}")

    print("Done")


if __name__ == '__main__':
    main()
