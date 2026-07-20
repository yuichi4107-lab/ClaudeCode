"""オートレース週次更新オーケストレータ(GitHub Actions から実行する純Python)。

1. DB接続 + init_db(スキーマ・マイグレーション適用)
2. 収集窓の決定: from = MAX(race_date) − 2日(DBが空なら昨日−7日)、to = 昨日(JST)
3. clear_recent_not_found: 結果未確定のうちに「データなし」を踏んだレースを再チェック対象に戻す
4. scrape_races(結果+補足情報)→ scrape_programs(出走表: 車級・期別等)
5. 直近365日ローリングで evaluate → data/reports/autorace_eval_latest.csv /
   autorace_rookie_latest.csv(固定名。ワークフローが差分コミットする)
6. WALチェックポイント(DBを単一ファイルに畳む。gzip保存の前提)

収集エラーは scrape_log に残り翌週の実行が拾うため、部分失敗でも exit 0。
例外による致命的失敗のみ exit 1。
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

# リポジトリルートを import パスに含める(Actions では checkout 直下で実行)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

EVAL_WINDOW_DAYS = 365
OVERLAP_DAYS = 2          # 前回収集の取りこぼし(未確定→確定)を拾う重なり
BOOTSTRAP_DAYS = 7        # DBが空のときの初期収集幅


def compute_scrape_window(max_race_date: str | None, today_jst: date) -> tuple[str, str]:
    """(from_date, to_date) を返す純関数。to は昨日。"""
    to_d = today_jst - timedelta(days=1)
    if max_race_date:
        from_d = date.fromisoformat(max_race_date) - timedelta(days=OVERLAP_DAYS)
    else:
        from_d = to_d - timedelta(days=BOOTSTRAP_DAYS)
    if from_d > to_d:
        from_d = to_d
    return from_d.isoformat(), to_d.isoformat()


def main() -> int:
    import pandas as pd

    from autorace_evaluator.config import settings
    from autorace_evaluator.metrics import report as report_mod
    from autorace_evaluator.metrics import rookie as rookie_mod
    from autorace_evaluator.metrics.meeting import update_meeting_ids
    from autorace_evaluator.scraper.race_program import scrape_programs
    from autorace_evaluator.scraper.race_result import scrape_races
    from autorace_evaluator.storage import database, repository

    conn = database.get_connection(settings.DB_PATH)
    database.init_db(conn)

    row = conn.execute("SELECT MAX(race_date) AS d FROM races").fetchone()
    today_jst = datetime.now(ZoneInfo("Asia/Tokyo")).date()
    from_date, to_date = compute_scrape_window(row["d"], today_jst)
    print(f"[weekly] scrape window: {from_date} .. {to_date}")

    cleared = repository.clear_recent_not_found(conn, from_date, to_date)
    print(f"[weekly] re-check targets restored: {cleared}")
    conn.close()

    stats = scrape_races(
        from_date, to_date, settings.VENUE_SLUGS,
        use_cache=False, progress=False,
    )
    print(f"[weekly] scrape_races: {stats}")

    pstats = scrape_programs(
        from_date, to_date, settings.VENUE_SLUGS,
        use_cache=False, progress=False,
    )
    print(f"[weekly] scrape_programs: {pstats}")

    # 直近365日ローリングで評価
    eval_to = to_date
    eval_from = (date.fromisoformat(to_date) - timedelta(days=EVAL_WINDOW_DAYS - 1)).isoformat()
    conn = database.get_connection(settings.DB_PATH)
    try:
        update_meeting_ids(conn)
        rows = repository.get_entries_with_race(conn, eval_from, eval_to)
        if not rows:
            print("[weekly] 評価対象データがありません")
            return 1
        entries_df = pd.DataFrame([dict(r) for r in rows])

        rep = report_mod.build_report(entries_df)
        report_dir = Path(settings.REPORT_DIR)
        report_mod.to_csv(rep, str(report_dir / "autorace_eval_latest.csv"))
        print(f"[weekly] eval rows: {len(rep['table'])} ({eval_from}..{eval_to})")

        rookie_rep = rookie_mod.build_rookie_report(entries_df)
        if not rookie_rep["table"].empty:
            report_mod.to_csv(rookie_rep, str(report_dir / "autorace_rookie_latest.csv"))
            print(f"[weekly] rookie rows: {len(rookie_rep['table'])}")

        # -wal を本体に畳む(この後 gzip して autorace-data ブランチへ保存するため)
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()

    if stats["errors"] or pstats["errors"]:
        print("[weekly] 一部エラーあり(scrape_log に記録済み、翌週の実行が再試行します)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
