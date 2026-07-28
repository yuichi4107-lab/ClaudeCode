"""SQLiteデータベーススキーマ定義"""

import sqlite3
import os

from src.utils.logger import setup_logger

logger = setup_logger(__name__)

TABLES_SQL = [
    # レース情報テーブル
    """
    CREATE TABLE IF NOT EXISTS races (
        race_id TEXT PRIMARY KEY,
        race_date DATE NOT NULL,
        venue_code TEXT NOT NULL,
        venue_name TEXT NOT NULL,
        kai INTEGER,
        nichi INTEGER,
        race_number INTEGER NOT NULL,
        race_name TEXT,
        grade TEXT,
        race_type TEXT,
        distance INTEGER,
        direction TEXT,
        track_condition TEXT,
        weather TEXT,
        horse_count INTEGER,
        prize_1st INTEGER
    )
    """,

    # レース結果テーブル
    """
    CREATE TABLE IF NOT EXISTS race_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        race_id TEXT NOT NULL,
        horse_id TEXT,
        horse_name TEXT,
        finish_order INTEGER,
        frame_number INTEGER,
        horse_number INTEGER,
        sex_age TEXT,
        weight_carry REAL,
        jockey_id TEXT,
        jockey_name TEXT,
        trainer_id TEXT,
        trainer_name TEXT,
        finish_time REAL,
        margin TEXT,
        corner_positions TEXT,
        final_3f REAL,
        horse_weight INTEGER,
        weight_change INTEGER,
        odds REAL,
        popularity INTEGER,
        FOREIGN KEY (race_id) REFERENCES races(race_id),
        UNIQUE(race_id, horse_number)
    )
    """,

    # 払戻テーブル
    """
    CREATE TABLE IF NOT EXISTS payoffs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        race_id TEXT NOT NULL,
        bet_type TEXT NOT NULL,
        combination TEXT NOT NULL,
        payout INTEGER,
        popularity INTEGER,
        FOREIGN KEY (race_id) REFERENCES races(race_id),
        UNIQUE(race_id, bet_type, combination)
    )
    """,

    # 馬の出走履歴テーブル
    """
    CREATE TABLE IF NOT EXISTS horse_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        horse_id TEXT NOT NULL,
        race_id TEXT,
        race_date DATE,
        venue_name TEXT,
        race_type TEXT,
        distance INTEGER,
        track_condition TEXT,
        finish_order INTEGER,
        horse_count INTEGER,
        finish_time REAL,
        final_3f REAL,
        horse_weight INTEGER,
        odds REAL,
        popularity INTEGER,
        jockey_name TEXT
    )
    """,

    # スクレイピングログテーブル
    """
    CREATE TABLE IF NOT EXISTS scrape_log (
        race_id TEXT PRIMARY KEY,
        status TEXT NOT NULL,
        scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        error_message TEXT
    )
    """,
]

INDEXES_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_races_date ON races(race_date)",
    "CREATE INDEX IF NOT EXISTS idx_races_venue ON races(venue_code)",
    "CREATE INDEX IF NOT EXISTS idx_races_date_venue ON races(race_date, venue_code)",
    "CREATE INDEX IF NOT EXISTS idx_race_results_race_id ON race_results(race_id)",
    "CREATE INDEX IF NOT EXISTS idx_race_results_horse_id ON race_results(horse_id)",
    "CREATE INDEX IF NOT EXISTS idx_race_results_jockey_id ON race_results(jockey_id)",
    "CREATE INDEX IF NOT EXISTS idx_race_results_trainer_id ON race_results(trainer_id)",
    "CREATE INDEX IF NOT EXISTS idx_payoffs_race_id ON payoffs(race_id)",
    "CREATE INDEX IF NOT EXISTS idx_horse_history_horse_id ON horse_history(horse_id)",
    "CREATE INDEX IF NOT EXISTS idx_horse_history_race_date ON horse_history(race_date)",
    "CREATE INDEX IF NOT EXISTS idx_horse_history_horse_date ON horse_history(horse_id, race_date)",
    "CREATE INDEX IF NOT EXISTS idx_scrape_log_status ON scrape_log(status)",
]


def create_tables(db_path: str) -> None:
    """全テーブルとインデックスを作成する"""
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")

        for sql in TABLES_SQL:
            cursor.execute(sql)

        for sql in INDEXES_SQL:
            cursor.execute(sql)

        conn.commit()
        logger.info("Database tables created at %s", db_path)
    finally:
        conn.close()
