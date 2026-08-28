"""storage/database.py のスキーマ・マイグレーションのテスト。"""

import sqlite3

from autorace_evaluator.storage import database, repository

# 旧スキーマ(Program列追加前)の race_entries 定義。マイグレーションの
# 適用対象を再現するためにテスト内に固定で保持する。
_OLD_SCHEMA_SQL = """
CREATE TABLE players (
    player_no    INTEGER PRIMARY KEY,
    player_name  TEXT NOT NULL,
    updated_at   TEXT
);
CREATE TABLE races (
    race_id        TEXT PRIMARY KEY,
    venue          TEXT NOT NULL,
    race_date      TEXT NOT NULL,
    race_no        INTEGER NOT NULL,
    race_name      TEXT,
    distance       INTEGER,
    weather        TEXT,
    track_status   TEXT,
    trial_track_status TEXT,
    temperature    REAL,
    track_temp     REAL,
    meeting_id     TEXT,
    field_size     INTEGER,
    source_url     TEXT,
    scraped_at     TEXT
);
CREATE TABLE race_entries (
    race_id        TEXT NOT NULL REFERENCES races(race_id),
    car_no         INTEGER NOT NULL,
    player_no      INTEGER REFERENCES players(player_no),
    player_name    TEXT,
    handicap       INTEGER,
    trial_time     REAL,
    is_retrial     INTEGER DEFAULT 0,
    race_time      REAL,
    last_lap_time  REAL,
    st             REAL,
    is_flying      INTEGER DEFAULT 0,
    finish_pos     INTEGER,
    status         TEXT NOT NULL DEFAULT 'finished',
    violation_note TEXT,
    PRIMARY KEY (race_id, car_no)
);
CREATE TABLE scrape_log (
    url         TEXT PRIMARY KEY,
    scraped_at  TEXT,
    status_code INTEGER,
    error_msg   TEXT
);
"""


def _entry_columns(conn) -> set:
    return {row["name"] for row in conn.execute("PRAGMA table_info(race_entries)")}


def test_new_db_has_program_columns():
    conn = database.get_connection(":memory:")
    database.init_db(conn)
    cols = _entry_columns(conn)
    assert set(database.RACE_ENTRIES_ADDED_COLUMNS) <= cols


def test_migration_adds_columns_to_old_schema():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(_OLD_SCHEMA_SQL)
    assert "bike_class" not in _entry_columns(conn)

    database.init_db(conn)
    cols = _entry_columns(conn)
    assert set(database.RACE_ENTRIES_ADDED_COLUMNS) <= cols

    # 冪等性: 2回目でも例外なく同じ列構成
    database.init_db(conn)
    assert _entry_columns(conn) == cols


def test_migration_preserves_existing_rows():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(_OLD_SCHEMA_SQL)
    conn.execute(
        "INSERT INTO races (race_id, venue, race_date, race_no) "
        "VALUES ('kawaguchi_2026-01-01_1', 'kawaguchi', '2026-01-01', 1)")
    conn.execute(
        "INSERT INTO race_entries (race_id, car_no, trial_time) "
        "VALUES ('kawaguchi_2026-01-01_1', 1, 3.31)")

    database.init_db(conn)
    row = conn.execute("SELECT * FROM race_entries").fetchone()
    assert row["trial_time"] == 3.31
    assert row["bike_class"] is None


def test_reupsert_entries_preserves_program_fields():
    """結果を再取得しても Program 由来列が消えない(REPLACE回帰の検出)。"""
    conn = database.get_connection(":memory:")
    database.init_db(conn)
    repository.upsert_race(conn, {
        "race_id": "kawaguchi_2026-01-01_1", "venue": "kawaguchi",
        "race_date": "2026-01-01", "race_no": 1,
    })
    entries = [{"car_no": 1, "player_no": None, "trial_time": 3.31,
                "finish_pos": 1, "status": "finished"}]
    repository.upsert_entries(conn, "kawaguchi_2026-01-01_1", entries)

    n = repository.update_entry_program_fields(conn, "kawaguchi_2026-01-01_1", [
        {"car_no": 1, "bike_class": "2級車", "graduation_code": 38,
         "player_rank": "B-140", "age": 22, "rate2": 5.0, "rate3": 15.0},
    ])
    assert n == 1

    # 結果を再upsert(値も更新されることを確認しつつ)
    entries2 = [{"car_no": 1, "player_no": None, "trial_time": 3.29,
                 "finish_pos": 2, "status": "finished"}]
    repository.upsert_entries(conn, "kawaguchi_2026-01-01_1", entries2)

    row = conn.execute("SELECT * FROM race_entries").fetchone()
    assert row["trial_time"] == 3.29
    assert row["finish_pos"] == 2
    assert row["bike_class"] == "2級車"
    assert row["graduation_code"] == 38
    assert row["rate3"] == 15.0


def test_update_program_fields_unmatched_rows_return_zero():
    conn = database.get_connection(":memory:")
    database.init_db(conn)
    n = repository.update_entry_program_fields(conn, "nonexistent_race", [
        {"car_no": 1, "bike_class": "1級車"},
    ])
    assert n == 0


def test_clear_recent_not_found():
    conn = database.get_connection(":memory:")
    database.init_db(conn)
    url_404 = "https://autorace.jp/race_info/RaceResult/kawaguchi/2026-01-02_5"
    url_cancel = "https://autorace.jp/race_info/RaceResult/kawaguchi/2026-01-02_6"
    url_outside = "https://autorace.jp/race_info/RaceResult/kawaguchi/2026-02-01_1"
    repository.log_scrape(conn, url_404, status_code=404, error_msg="データなし(4101)")
    repository.log_scrape(conn, url_cancel, status_code=404, error_msg="中止(4200)")
    repository.log_scrape(conn, url_outside, status_code=404, error_msg="HTTP 404")

    deleted = repository.clear_recent_not_found(conn, "2026-01-01", "2026-01-03")
    assert deleted == 1
    assert not repository.was_scraped(conn, url_404)      # 再チェック対象に戻る
    assert repository.was_scraped(conn, url_cancel)       # 中止は残る
    assert repository.was_scraped(conn, url_outside)      # 期間外は残る
