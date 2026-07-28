"""win5.db への移植結果を件数・整合で検証する。"""

import argparse
import sqlite3


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--win5-db", default="data/win5.db")
    args = ap.parse_args()

    c = sqlite3.connect(args.win5_db)
    races = c.execute("SELECT COUNT(*) FROM races").fetchone()[0]
    results = c.execute("SELECT COUNT(*) FROM race_results").fetchone()[0]
    winners = c.execute("SELECT COUNT(*) FROM race_results WHERE finish_position=1").fetchone()[0]
    null_odds = c.execute("SELECT COUNT(*) FROM race_results WHERE odds IS NULL").fetchone()[0]
    dmin, dmax = c.execute("SELECT MIN(race_date), MAX(race_date) FROM races").fetchone()
    c.close()

    print(f"races={races} results={results} winners(1着)={winners}")
    print(f"date_range={dmin}..{dmax} null_odds={null_odds}")
    assert races > 15000, "races が想定（>15000）未満。移植失敗の可能性"
    assert results > 200000, "results が想定（>200000）未満"
    assert winners >= races * 0.9, "1着レコード数が不足（レースあたり1着が欠損）"
    print("VERIFY OK")


if __name__ == "__main__":
    main()
