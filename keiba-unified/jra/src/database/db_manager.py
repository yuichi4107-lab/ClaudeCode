"""データベース操作管理モジュール"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Dict, List, Optional

from src.database.schema import create_tables
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class DBManager:
    """SQLiteデータベースの操作を管理するクラス"""

    def __init__(self, db_path: str):
        self.db_path = db_path

    @contextmanager
    def _connect(self):
        """コンテキストマネージャでDB接続を管理する"""
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=10000")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_db(self) -> None:
        """データベースを初期化する"""
        create_tables(self.db_path)
        logger.info("Database initialized: %s", self.db_path)

    # ---- Insert methods ----

    def insert_race(self, data: Dict) -> None:
        """レース情報を挿入または更新する"""
        sql = """
            INSERT OR REPLACE INTO races (
                race_id, race_date, venue_code, venue_name, kai, nichi,
                race_number, race_name, grade, race_type, distance, direction,
                track_condition, weather, horse_count, prize_1st
            ) VALUES (
                :race_id, :race_date, :venue_code, :venue_name, :kai, :nichi,
                :race_number, :race_name, :grade, :race_type, :distance, :direction,
                :track_condition, :weather, :horse_count, :prize_1st
            )
        """
        with self._connect() as conn:
            conn.execute(sql, data)

    def insert_race_result(self, data: Dict) -> None:
        """レース結果を1件挿入する"""
        sql = """
            INSERT OR REPLACE INTO race_results (
                race_id, horse_id, horse_name, finish_order, frame_number,
                horse_number, sex_age, weight_carry, jockey_id, jockey_name,
                trainer_id, trainer_name, finish_time, margin, corner_positions,
                final_3f, horse_weight, weight_change, odds, popularity
            ) VALUES (
                :race_id, :horse_id, :horse_name, :finish_order, :frame_number,
                :horse_number, :sex_age, :weight_carry, :jockey_id, :jockey_name,
                :trainer_id, :trainer_name, :finish_time, :margin, :corner_positions,
                :final_3f, :horse_weight, :weight_change, :odds, :popularity
            )
        """
        with self._connect() as conn:
            conn.execute(sql, data)

    def insert_race_results_batch(self, results: List[Dict]) -> None:
        """レース結果を一括挿入する"""
        if not results:
            return
        sql = """
            INSERT OR REPLACE INTO race_results (
                race_id, horse_id, horse_name, finish_order, frame_number,
                horse_number, sex_age, weight_carry, jockey_id, jockey_name,
                trainer_id, trainer_name, finish_time, margin, corner_positions,
                final_3f, horse_weight, weight_change, odds, popularity
            ) VALUES (
                :race_id, :horse_id, :horse_name, :finish_order, :frame_number,
                :horse_number, :sex_age, :weight_carry, :jockey_id, :jockey_name,
                :trainer_id, :trainer_name, :finish_time, :margin, :corner_positions,
                :final_3f, :horse_weight, :weight_change, :odds, :popularity
            )
        """
        with self._connect() as conn:
            conn.executemany(sql, results)

    def insert_payoff(self, data: Dict) -> None:
        """払戻データを1件挿入する"""
        sql = """
            INSERT OR REPLACE INTO payoffs (
                race_id, bet_type, combination, payout, popularity
            ) VALUES (
                :race_id, :bet_type, :combination, :payout, :popularity
            )
        """
        with self._connect() as conn:
            conn.execute(sql, data)

    def insert_payoffs_batch(self, payoffs: List[Dict]) -> None:
        """払戻データを一括挿入する"""
        if not payoffs:
            return
        sql = """
            INSERT OR REPLACE INTO payoffs (
                race_id, bet_type, combination, payout, popularity
            ) VALUES (
                :race_id, :bet_type, :combination, :payout, :popularity
            )
        """
        with self._connect() as conn:
            conn.executemany(sql, payoffs)

    def insert_horse_history(self, data: Dict) -> None:
        """馬の出走履歴を1件挿入する"""
        sql = """
            INSERT INTO horse_history (
                horse_id, race_id, race_date, venue_name, race_type, distance,
                track_condition, finish_order, horse_count, finish_time,
                final_3f, horse_weight, odds, popularity, jockey_name
            ) VALUES (
                :horse_id, :race_id, :race_date, :venue_name, :race_type, :distance,
                :track_condition, :finish_order, :horse_count, :finish_time,
                :final_3f, :horse_weight, :odds, :popularity, :jockey_name
            )
        """
        with self._connect() as conn:
            conn.execute(sql, data)

    def insert_horse_history_batch(self, histories: List[Dict]) -> None:
        """馬の出走履歴を一括挿入する"""
        if not histories:
            return
        sql = """
            INSERT INTO horse_history (
                horse_id, race_id, race_date, venue_name, race_type, distance,
                track_condition, finish_order, horse_count, finish_time,
                final_3f, horse_weight, odds, popularity, jockey_name
            ) VALUES (
                :horse_id, :race_id, :race_date, :venue_name, :race_type, :distance,
                :track_condition, :finish_order, :horse_count, :finish_time,
                :final_3f, :horse_weight, :odds, :popularity, :jockey_name
            )
        """
        with self._connect() as conn:
            conn.executemany(sql, histories)

    def update_scrape_log(
        self, race_id: str, status: str, error: Optional[str] = None
    ) -> None:
        """スクレイピングログを更新する"""
        sql = """
            INSERT OR REPLACE INTO scrape_log (race_id, status, scraped_at, error_message)
            VALUES (?, ?, ?, ?)
        """
        with self._connect() as conn:
            conn.execute(sql, (race_id, status, datetime.now().isoformat(), error))

    # ---- Query methods ----

    def get_race(self, race_id: str) -> Optional[Dict]:
        """レース情報を取得する"""
        sql = "SELECT * FROM races WHERE race_id = ?"
        with self._connect() as conn:
            row = conn.execute(sql, (race_id,)).fetchone()
            return dict(row) if row else None

    def get_race_results(self, race_id: str) -> List[Dict]:
        """レース結果を取得する"""
        sql = """
            SELECT * FROM race_results
            WHERE race_id = ?
            ORDER BY finish_order
        """
        with self._connect() as conn:
            rows = conn.execute(sql, (race_id,)).fetchall()
            return [dict(r) for r in rows]

    def get_payoffs(self, race_id: str) -> List[Dict]:
        """払戻データを取得する"""
        sql = "SELECT * FROM payoffs WHERE race_id = ?"
        with self._connect() as conn:
            rows = conn.execute(sql, (race_id,)).fetchall()
            return [dict(r) for r in rows]

    def get_horse_history(
        self, horse_id: str, before_date: Optional[str] = None
    ) -> List[Dict]:
        """馬の出走履歴を取得する"""
        if before_date:
            sql = """
                SELECT * FROM horse_history
                WHERE horse_id = ? AND race_date < ?
                ORDER BY race_date DESC
            """
            params = (horse_id, before_date)
        else:
            sql = """
                SELECT * FROM horse_history
                WHERE horse_id = ?
                ORDER BY race_date DESC
            """
            params = (horse_id,)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]

    def get_races_by_date_range(self, start: str, end: str) -> List[Dict]:
        """日付範囲内のレース情報を取得する"""
        sql = """
            SELECT * FROM races
            WHERE race_date BETWEEN ? AND ?
            ORDER BY race_date, venue_code, race_number
        """
        with self._connect() as conn:
            rows = conn.execute(sql, (start, end)).fetchall()
            return [dict(r) for r in rows]

    def get_all_race_ids(self) -> List[str]:
        """全レースIDを取得する"""
        sql = "SELECT race_id FROM races ORDER BY race_id"
        with self._connect() as conn:
            rows = conn.execute(sql).fetchall()
            return [r["race_id"] for r in rows]

    def get_pending_scrape_ids(self) -> List[str]:
        """スクレイピング未完了のレースIDを取得する"""
        sql = """
            SELECT race_id FROM scrape_log
            WHERE status != 'done'
            ORDER BY race_id
        """
        with self._connect() as conn:
            rows = conn.execute(sql).fetchall()
            return [r["race_id"] for r in rows]

    def get_scraped_race_ids(self) -> set:
        """スクレイピング完了済みのレースIDセットを取得する"""
        sql = "SELECT race_id FROM scrape_log WHERE status = 'done'"
        with self._connect() as conn:
            rows = conn.execute(sql).fetchall()
            return {r["race_id"] for r in rows}
