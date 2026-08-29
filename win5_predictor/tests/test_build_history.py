"""build_history.py（DB→較正CSV）のテスト。"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from build_history import build  # noqa: E402


def _make_db(path):
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE races(race_id TEXT PRIMARY KEY, race_date DATE);
        CREATE TABLE race_results(
            race_id TEXT, horse_number INT, odds REAL, finish_position INT
        );
        """
    )
    conn.executemany("INSERT INTO races VALUES(?,?)", [
        ("R1", "2025-01-01"), ("R2", "2025-02-01"), ("R3", "2025-03-01"),
    ])
    conn.executemany(
        "INSERT INTO race_results VALUES(?,?,?,?)",
        [
            # R1: 正常（3頭・勝ち馬1頭）
            ("R1", 1, 2.0, 1), ("R1", 2, 3.0, 2), ("R1", 3, 9.0, 3),
            # R2: odds 欠損や 1.0 以下は除外され勝ち馬無し → スキップ
            ("R2", 1, None, 1), ("R2", 2, 1.0, 2),
            # R3: 勝ち馬2頭（異常）→ スキップ
            ("R3", 1, 2.0, 1), ("R3", 2, 3.0, 1),
        ],
    )
    conn.commit()
    conn.close()


def test_build_keeps_valid_races(tmp_path):
    db = tmp_path / "t.db"
    _make_db(str(db))
    rows, kept, skipped = build(str(db))
    assert kept == 1
    # R2 は odds 欠損/≤1.0 で SQL 段階で全行除外され by_race に現れない。
    # R3 は勝ち馬2頭で skipped。よって skipped == 1。
    assert skipped == 1
    # ヘッダ + R1 の3頭
    assert rows[0] == ("race_id", "odds", "won")
    data = rows[1:]
    assert len(data) == 3
    assert sum(r[2] for r in data) == 1  # 勝ち馬1頭
    won_row = [r for r in data if r[2] == 1][0]
    assert won_row[1] == 2.0  # 最低オッズ馬が勝ち


def test_date_filter(tmp_path):
    db = tmp_path / "t.db"
    _make_db(str(db))
    rows, kept, skipped = build(str(db), start="2025-02-01")
    assert kept == 0  # R1(1月)は除外、R2/R3は元々スキップ
