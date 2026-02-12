import sqlite3
from pathlib import Path
from nankan_predictor.config.settings import DB_PATH

CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS races (
    race_id          TEXT PRIMARY KEY,
    venue_code       TEXT NOT NULL,
    venue_name       TEXT,
    race_date        TEXT NOT NULL,
    race_number      INTEGER,
    race_name        TEXT,
    distance         INTEGER,
    track_type       TEXT,
    track_condition  TEXT,
    weather          TEXT,
    field_size       INTEGER,
    scraped_at       TEXT
);

CREATE TABLE IF NOT EXISTS horses (
    horse_id    TEXT PRIMARY KEY,
    horse_name  TEXT NOT NULL,
    updated_at  TEXT
);

CREATE TABLE IF NOT EXISTS jockeys (
    jockey_id   TEXT PRIMARY KEY,
    jockey_name TEXT NOT NULL,
    updated_at  TEXT
);

CREATE TABLE IF NOT EXISTS race_entries (
    entry_id          TEXT PRIMARY KEY,
    race_id           TEXT NOT NULL REFERENCES races(race_id),
    horse_id          TEXT REFERENCES horses(horse_id),
    jockey_id         TEXT REFERENCES jockeys(jockey_id),
    horse_name        TEXT,
    jockey_name       TEXT,
    trainer_name      TEXT,
    gate_number       INTEGER,
    horse_number      INTEGER,
    weight_carried    REAL,
    horse_weight      INTEGER,
    weight_change     INTEGER,
    win_odds          REAL,
    popularity_rank   INTEGER,
    finish_position   INTEGER,
    finish_time       REAL,
    margin            TEXT,
    passing_positions TEXT,
    last_3f_time      REAL,
    horse_age         INTEGER,
    horse_sex         TEXT,
    is_winner         INTEGER
);

CREATE TABLE IF NOT EXISTS horse_history_cache (
    horse_id          TEXT NOT NULL,
    race_date         TEXT NOT NULL,
    venue_name        TEXT,
    race_name         TEXT,
    distance          INTEGER,
    field_size        INTEGER,
    gate_number       INTEGER,
    horse_number      INTEGER,
    popularity_rank   INTEGER,
    finish_position   INTEGER,
    jockey_name       TEXT,
    weight_carried    REAL,
    finish_time       REAL,
    margin            TEXT,
    passing_positions TEXT,
    pace              TEXT,
    horse_weight      INTEGER,
    PRIMARY KEY (horse_id, race_date, race_name)
);

CREATE TABLE IF NOT EXISTS race_payouts (
    race_id         TEXT NOT NULL,
    bet_type        TEXT NOT NULL,  -- "exacta" (馬単), "win" (単勝) 等
    combination     TEXT NOT NULL,  -- "3-7" (馬番1着-2着) 等
    payout          REAL,           -- 払戻金額（100円あたり）
    PRIMARY KEY (race_id, bet_type, combination)
);

CREATE TABLE IF NOT EXISTS scrape_log (
    url         TEXT PRIMARY KEY,
    scraped_at  TEXT,
    status_code INTEGER,
    error_msg   TEXT
);
"""


def get_connection(db_path: str = DB_PATH) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: str = DB_PATH) -> None:
    conn = get_connection(db_path)
    conn.executescript(CREATE_TABLES_SQL)
    conn.commit()
    conn.close()
