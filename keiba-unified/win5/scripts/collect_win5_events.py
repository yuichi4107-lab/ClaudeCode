"""WIN5履歴イベント収集スクリプト

使い方:
    PYTHONPATH=src python scripts/collect_win5_events.py
    PYTHONPATH=src python scripts/collect_win5_events.py --start-year 2024 --end-year 2026

年ごとに list_win5_dates() → scrape() → upsert_win5_event() を実行。
収集後、2026分の CSV 突合を実施してサマリを出力する。
"""

import argparse
import logging
import sys
import time
from datetime import date
from pathlib import Path

# PYTHONPATH=src で実行される前提
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="WIN5 履歴イベント収集")
    p.add_argument("--start-year", type=int, default=2021)
    p.add_argument("--end-year", type=int, default=2026)
    p.add_argument("--win5-db", default="data/win5.db")
    p.add_argument("--csv", default="data/win5_results_2026.csv")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    # ── DB・リポジトリ初期化 ──────────────────────────────
    from database.connection import Database
    from database.repository import Repository

    db = Database(db_path=args.win5_db)
    db.initialize()
    repo = Repository(db)

    # win5_events は race_id に対して FOREIGN KEY 制約を持つが、
    # 2026年など手元DBに未収録の race_id が存在する場合は挿入できない。
    # 収集スクリプトでは FK 制約を一時無効にして挿入し、
    # 未連結件数を後で報告する（assertで全件連結を強制しない）。
    def upsert_win5_event_no_fk(event):
        """FOREIGN KEY 制約を無効にして Win5Event を upsert する"""
        import sqlite3
        from dataclasses import asdict

        d = asdict(event)
        # date型をISOformat文字列に変換
        if hasattr(d.get("event_date"), "isoformat"):
            d["event_date"] = d["event_date"].isoformat()

        cols = ", ".join(d.keys())
        placeholders = ", ".join(["?"] * len(d))
        update = ", ".join(f"{k}=excluded.{k}" for k in d if k != "event_id")
        sql = (
            f"INSERT INTO win5_events ({cols}) VALUES ({placeholders}) "
            f"ON CONFLICT(event_id) DO UPDATE SET {update}"
        )

        conn = sqlite3.connect(args.win5_db)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            conn.execute(sql, list(d.values()))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ── スクレイパー初期化（キャッシュ有効） ─────────────
    from scraper.win5_target import Win5TargetScraper
    from config.settings import REQUEST_INTERVAL_SEC

    scraper = Win5TargetScraper(use_cache=True)

    # ── 収集ループ ────────────────────────────────────────
    total_events = 0
    total_skipped = 0
    total_error = 0

    for year in range(args.start_year, args.end_year + 1):
        logger.info("=== %d 年 WIN5 収集開始 ===", year)
        dates = scraper.list_win5_dates(year)
        if not dates:
            logger.warning("%d 年: 開催日が取得できませんでした", year)
            continue

        year_events = 0
        year_skipped = 0
        year_error = 0

        for d in dates:
            try:
                time.sleep(REQUEST_INTERVAL_SEC)
                ev = scraper.scrape(d)
                if ev is None:
                    logger.warning("  %s: スキップ (1レース未満または取得失敗)", d)
                    year_skipped += 1
                    total_skipped += 1
                    continue
                upsert_win5_event_no_fk(ev)
                year_events += 1
                total_events += 1
            except Exception as e:
                logger.error("  %s: エラー - %s", d, e)
                year_error += 1
                total_error += 1

        logger.info(
            "  %d 年完了: 収集=%d / スキップ=%d / エラー=%d",
            year,
            year_events,
            year_skipped,
            year_error,
        )

    logger.info(
        "=== 全収集完了: 合計 %d 件, スキップ %d 件, エラー %d 件 ===",
        total_events,
        total_skipped,
        total_error,
    )

    # ── DBサマリ ─────────────────────────────────────────
    import sqlite3

    conn = sqlite3.connect(args.win5_db)
    cur = conn.cursor()
    events_count = cur.execute("SELECT count(*) FROM win5_events").fetchone()[0]
    with_payout = cur.execute(
        "SELECT count(*) FROM win5_events WHERE payout IS NOT NULL"
    ).fetchone()[0]
    race5_linked = cur.execute(
        "SELECT count(*) FROM win5_events e "
        "WHERE EXISTS(SELECT 1 FROM races r WHERE r.race_id=e.race5_id)"
    ).fetchone()[0]
    conn.close()

    print(f"\n--- DB サマリ ---")
    print(f"events      : {events_count}")
    print(f"with_payout : {with_payout}")
    print(f"race5_linked: {race5_linked}")
    if events_count > 0:
        unlinked = events_count - race5_linked
        print(f"  未連結    : {unlinked} 件 (2026年直近DB未収録などは許容)")

    # ── 2026 CSV 突合 ────────────────────────────────────
    csv_path = Path(args.csv)
    if not csv_path.exists():
        logger.warning("CSV ファイルが見つかりません: %s (突合スキップ)", csv_path)
        return

    from etl.win5_results_csv import load_win5_results
    from etl.event_crosscheck import crosscheck_payouts

    try:
        csv_rows = load_win5_results(str(csv_path))
    except Exception as e:
        logger.error("CSV 読み込み失敗: %s", e)
        return

    if not csv_rows:
        logger.info("CSV が空のため突合スキップ")
        return

    # 2026年分のイベントを取得
    events_2026 = repo.get_win5_events_in_range(date(2026, 1, 1), date(2026, 12, 31))
    mismatches = crosscheck_payouts(events_2026, csv_rows)

    print(f"\n--- 2026 CSV 突合 ---")
    print(f"CSVレコード数  : {len(csv_rows)}")
    print(f"DB 2026 events: {len(events_2026)}")
    print(f"不一致件数     : {len(mismatches)}")
    if mismatches:
        print("  [不一致一覧]")
        for d, ev_pay, csv_pay in mismatches[:10]:
            print(f"    {d}: DB={ev_pay}, CSV={csv_pay}")
    else:
        print("  -> 全件一致 (または突合対象なし)")


if __name__ == "__main__":
    main()
