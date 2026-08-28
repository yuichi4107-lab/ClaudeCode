import sqlite3
from pathlib import Path

from autorace_evaluator.config.settings import DB_PATH

CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS players (
    player_no    INTEGER PRIMARY KEY,
    player_name  TEXT NOT NULL,
    updated_at   TEXT
);

CREATE TABLE IF NOT EXISTS races (
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

CREATE TABLE IF NOT EXISTS race_entries (
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
    bike_class     TEXT,
    graduation_code INTEGER,
    player_rank    TEXT,
    age            INTEGER,
    rate2          REAL,
    rate3          REAL,
    PRIMARY KEY (race_id, car_no)
);

CREATE TABLE IF NOT EXISTS payouts (
    race_id     TEXT NOT NULL REFERENCES races(race_id),
    bet_type    TEXT NOT NULL,
    combination TEXT NOT NULL,
    payout      REAL,
    PRIMARY KEY (race_id, bet_type, combination)
);

CREATE TABLE IF NOT EXISTS exacta_odds (
    race_id     TEXT NOT NULL REFERENCES races(race_id),
    first       INTEGER NOT NULL,
    second      INTEGER NOT NULL,
    odds        REAL,
    status_code INTEGER,           -- 0=中間オッズ, 1=最終オッズ
    updated_at  TEXT,              -- salesInfo.updateDate
    PRIMARY KEY (race_id, first, second)
);

CREATE TABLE IF NOT EXISTS win_odds (
    race_id     TEXT NOT NULL REFERENCES races(race_id),
    car_no      INTEGER NOT NULL,
    odds        REAL,
    status_code INTEGER,
    updated_at  TEXT,
    PRIMARY KEY (race_id, car_no)
);

CREATE TABLE IF NOT EXISTS scrape_log (
    url         TEXT PRIMARY KEY,
    scraped_at  TEXT,
    status_code INTEGER,
    error_msg   TEXT
);

CREATE INDEX IF NOT EXISTS idx_entries_player ON race_entries(player_no);
CREATE INDEX IF NOT EXISTS idx_races_date ON races(race_date, venue);
"""


def get_connection(db_path: str | None = None) -> sqlite3.Connection:
    """DB接続を取得する(WAL・外部キー制約ON)。db_path 未指定時は settings.DB_PATH。"""
    if db_path is None:
        db_path = DB_PATH
    if db_path != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# 旧スキーマDBへ追補する列(列名 -> 型)。出走表(Program)API 由来。
# CREATE_TABLES_SQL の race_entries 定義と一致させること。
RACE_ENTRIES_ADDED_COLUMNS = {
    "bike_class": "TEXT",        # 車級の正規化ラベル("1級車"/"2級車"、未知はコード原文)
    "graduation_code": "INTEGER",  # 期別
    "player_rank": "TEXT",       # 級班(S-1/A-8 等)
    "age": "INTEGER",
    "rate2": "REAL",             # 2連対率(予想用に同時保存)
    "rate3": "REAL",             # 3連対率
}


def _migrate(conn: sqlite3.Connection) -> None:
    """CREATE IF NOT EXISTS では追補されない列を ALTER TABLE で追加する(冪等)。"""
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(race_entries)")}
    for col, typ in RACE_ENTRIES_ADDED_COLUMNS.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE race_entries ADD COLUMN {col} {typ}")


def init_db(conn: sqlite3.Connection) -> None:
    """テーブル・インデックスを作成し、旧スキーマには不足列を追補する。"""
    conn.executescript(CREATE_TABLES_SQL)
    _migrate(conn)
    conn.commit()
