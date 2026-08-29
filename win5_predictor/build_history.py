#!/usr/bin/env python3
"""SQLite の race_results から β 較正用の history CSV を生成する。

race_results（各馬の単勝オッズ odds と着順 finish_position）を元に、
race_id ごとに「全出走馬の odds ＋ 勝ち馬(won=1)」を書き出す。

使い方:
    python build_history.py [--db data/win5.db] [--out data/history.csv]
                            [--start 2020-01-01] [--end 2025-12-31]
出力 CSV 列: race_id, odds, won  → そのまま run_calibrate.py に渡せる。
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
from collections import defaultdict
from pathlib import Path


def build(db_path: str, start: str | None = None, end: str | None = None):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    q = (
        "SELECT r.race_id AS race_id, rr.horse_number AS hn, rr.odds AS odds, "
        "rr.finish_position AS fp "
        "FROM race_results rr JOIN races r ON r.race_id = rr.race_id "
        "WHERE rr.odds IS NOT NULL AND rr.odds > 1.0"
    )
    params: list = []
    if start:
        q += " AND r.race_date >= ?"
        params.append(start)
    if end:
        q += " AND r.race_date <= ?"
        params.append(end)
    q += " ORDER BY r.race_id, rr.horse_number"

    by_race: dict[str, list] = defaultdict(list)
    for row in conn.execute(q, params):
        by_race[row["race_id"]].append((row["odds"], row["fp"]))
    conn.close()

    rows = [("race_id", "odds", "won")]
    kept = skipped = 0
    for race_id, horses in by_race.items():
        winners = [1 for _, fp in horses if fp == 1]
        if len(horses) < 2 or sum(winners) != 1:
            skipped += 1
            continue
        kept += 1
        for odds, fp in horses:
            rows.append((race_id, odds, 1 if fp == 1 else 0))
    return rows, kept, skipped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/win5.db")
    ap.add_argument("--out", default="data/history.csv")
    ap.add_argument("--start", default=None, help="race_date 下限 (YYYY-MM-DD)")
    ap.add_argument("--end", default=None, help="race_date 上限 (YYYY-MM-DD)")
    args = ap.parse_args()

    if not Path(args.db).exists():
        print(f"⚠ DB が見つかりません: {args.db}")
        print("  先にデータ収集（scraper / win5 collect）で race_results を埋めてください。")
        return

    rows, kept, skipped = build(args.db, args.start, args.end)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", newline="") as f:
        csv.writer(f).writerows(rows)
    print(f"✅ {args.out} を出力（採用レース {kept}、除外 {skipped}）")
    if kept == 0:
        print("  ⚠ 採用レース 0。odds と finish_position が入っているか確認してください。")
    else:
        print(f"  次: python run_calibrate.py {args.out}")


if __name__ == "__main__":
    main()
