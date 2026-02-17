import sqlite3
from datetime import datetime
from typing import Optional
import pandas as pd

from jra_predictor.storage.database import get_connection
from jra_predictor.config.settings import DB_PATH


class Repository:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path

    def _conn(self) -> sqlite3.Connection:
        return get_connection(self.db_path)

    # ------------------------------------------------------------------ races

    def upsert_race(self, race_info: dict) -> None:
        sql = """
        INSERT INTO races (race_id, venue_code, venue_name, race_date, race_number,
                           race_name, race_class, distance, track_type, track_condition,
                           course_direction, weather, field_size, scraped_at)
        VALUES (:race_id, :venue_code, :venue_name, :race_date, :race_number,
                :race_name, :race_class, :distance, :track_type, :track_condition,
                :course_direction, :weather, :field_size, :scraped_at)
        ON CONFLICT(race_id) DO UPDATE SET
            venue_name       = excluded.venue_name,
            race_name        = excluded.race_name,
            race_class       = excluded.race_class,
            distance         = excluded.distance,
            track_type       = excluded.track_type,
            track_condition  = excluded.track_condition,
            course_direction = excluded.course_direction,
            weather          = excluded.weather,
            field_size       = excluded.field_size,
            scraped_at       = excluded.scraped_at
        """
        defaults = {
            "race_name": None, "race_class": None, "distance": None, "track_type": None,
            "track_condition": None, "course_direction": None,
            "weather": None, "field_size": None, "venue_name": None,
        }
        data = {**defaults, **race_info, "scraped_at": datetime.now().isoformat()}
        with self._conn() as conn:
            conn.execute(sql, data)

    def race_exists(self, race_id: str) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM races WHERE race_id = ?", (race_id,)
            ).fetchone()
        return row is not None

    # --------------------------------------------------------------- entries

    def upsert_entries(self, entries: list[dict]) -> None:
        sql = """
        INSERT INTO race_entries
            (entry_id, race_id, horse_id, jockey_id, horse_name, jockey_name,
             trainer_name, gate_number, horse_number, weight_carried, horse_weight,
             weight_change, win_odds, popularity_rank, finish_position, finish_time,
             margin, passing_positions, last_3f_time, horse_age, horse_sex, is_winner)
        VALUES
            (:entry_id, :race_id, :horse_id, :jockey_id, :horse_name, :jockey_name,
             :trainer_name, :gate_number, :horse_number, :weight_carried, :horse_weight,
             :weight_change, :win_odds, :popularity_rank, :finish_position, :finish_time,
             :margin, :passing_positions, :last_3f_time, :horse_age, :horse_sex, :is_winner)
        ON CONFLICT(entry_id) DO UPDATE SET
            finish_position   = excluded.finish_position,
            finish_time       = excluded.finish_time,
            win_odds          = excluded.win_odds,
            popularity_rank   = excluded.popularity_rank,
            horse_weight      = excluded.horse_weight,
            weight_change     = excluded.weight_change,
            is_winner         = excluded.is_winner
        """
        entry_defaults = {
            "horse_id": None, "jockey_id": None, "horse_name": None,
            "jockey_name": None, "trainer_name": None, "gate_number": None,
            "horse_number": None, "weight_carried": None, "horse_weight": None,
            "weight_change": None, "win_odds": None, "popularity_rank": None,
            "finish_position": None, "finish_time": None, "margin": None,
            "passing_positions": None, "last_3f_time": None,
            "horse_age": None, "horse_sex": None, "is_winner": None,
        }
        with self._conn() as conn:
            for entry in entries:
                entry = {**entry_defaults, **entry}
                if "entry_id" not in entry:
                    entry["entry_id"] = (
                        f"{entry['race_id']}_{entry.get('horse_number', 0):02d}"
                    )
                conn.execute(sql, entry)

    def upsert_horse(self, horse_id: str, horse_name: str) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO horses (horse_id, horse_name, updated_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(horse_id) DO NOTHING""",
                (horse_id, horse_name, datetime.now().isoformat()),
            )

    def upsert_jockey(self, jockey_id: str, jockey_name: str) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO jockeys (jockey_id, jockey_name, updated_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(jockey_id) DO NOTHING""",
                (jockey_id, jockey_name, datetime.now().isoformat()),
            )

    # ---------------------------------------------------- horse_history_cache

    def upsert_horse_history(self, horse_id: str, rows: list[dict]) -> None:
        sql = """
        INSERT INTO horse_history_cache
            (horse_id, race_date, venue_name, race_name, distance, track_type,
             field_size, gate_number, horse_number, popularity_rank, finish_position,
             jockey_name, weight_carried, finish_time, margin, passing_positions,
             pace, horse_weight)
        VALUES
            (:horse_id, :race_date, :venue_name, :race_name, :distance, :track_type,
             :field_size, :gate_number, :horse_number, :popularity_rank, :finish_position,
             :jockey_name, :weight_carried, :finish_time, :margin, :passing_positions,
             :pace, :horse_weight)
        ON CONFLICT(horse_id, race_date, race_name) DO NOTHING
        """
        with self._conn() as conn:
            for row in rows:
                row["horse_id"] = horse_id
                row.setdefault("track_type", "")
                conn.execute(sql, row)

    def horse_history_exists(self, horse_id: str) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM horse_history_cache WHERE horse_id = ? LIMIT 1",
                (horse_id,),
            ).fetchone()
        return row is not None

    # --------------------------------------------------------- query helpers

    def get_entries_in_range(
        self, from_date: str, to_date: str,
        exclude_classes: list[str] | None = None,
    ) -> pd.DataFrame:
        sql = """
        SELECT e.*, r.venue_code, r.venue_name, r.race_date, r.distance,
               r.track_type, r.track_condition, r.course_direction,
               r.field_size, r.race_number, r.race_class
        FROM race_entries e
        JOIN races r ON e.race_id = r.race_id
        WHERE r.race_date BETWEEN ? AND ?
          AND e.finish_position IS NOT NULL
        """
        params: list = [from_date, to_date]
        if exclude_classes:
            placeholders = ",".join("?" for _ in exclude_classes)
            sql += f"  AND (r.race_class IS NULL OR r.race_class NOT IN ({placeholders}))\n"
            params.extend(exclude_classes)
        # 障害レースは常に除外
        sql += "  AND r.track_type != '障害'\n"
        sql += "ORDER BY r.race_date, e.race_id, e.horse_number"
        with self._conn() as conn:
            return pd.read_sql_query(sql, conn, params=params)

    def get_horse_history(
        self,
        horse_id: str,
        before_date: str,
        limit: int = 20,
    ) -> pd.DataFrame:
        sql = """
        SELECT * FROM horse_history_cache
        WHERE horse_id = ? AND race_date < ?
        ORDER BY race_date DESC
        LIMIT ?
        """
        with self._conn() as conn:
            return pd.read_sql_query(
                sql, conn, params=(horse_id, before_date, limit)
            )

    def get_jockey_stats(
        self, jockey_id: str, before_date: str, venue_code: Optional[str] = None
    ) -> pd.DataFrame:
        if venue_code:
            sql = """
            SELECT e.finish_position, r.venue_code, r.distance
            FROM race_entries e
            JOIN races r ON e.race_id = r.race_id
            WHERE e.jockey_id = ? AND r.race_date < ? AND r.venue_code = ?
              AND e.finish_position IS NOT NULL
            """
            params = (jockey_id, before_date, venue_code)
        else:
            sql = """
            SELECT e.finish_position, r.venue_code, r.distance
            FROM race_entries e
            JOIN races r ON e.race_id = r.race_id
            WHERE e.jockey_id = ? AND r.race_date < ?
              AND e.finish_position IS NOT NULL
            """
            params = (jockey_id, before_date)
        with self._conn() as conn:
            return pd.read_sql_query(sql, conn, params=params)

    def get_race_entries(self, race_id: str) -> pd.DataFrame:
        sql = """
        SELECT e.*, r.venue_code, r.venue_name, r.race_date, r.distance,
               r.track_type, r.track_condition, r.course_direction,
               r.field_size, r.race_number
        FROM race_entries e
        JOIN races r ON e.race_id = r.race_id
        WHERE e.race_id = ?
        ORDER BY e.horse_number
        """
        with self._conn() as conn:
            return pd.read_sql_query(sql, conn, params=(race_id,))

    def upsert_payout(self, race_id: str, bet_type: str, combination: str, payout: float) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO race_payouts (race_id, bet_type, combination, payout)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(race_id, bet_type, combination) DO UPDATE SET payout=excluded.payout""",
                (race_id, bet_type, combination, payout),
            )

    def get_quinella_payout(self, race_id: str, h1: int, h2: int) -> float | None:
        """馬連払戻金を取得する。combination は馬番をソートした '小-大' 形式。"""
        sorted_nums = sorted([h1, h2])
        combination = f"{sorted_nums[0]}-{sorted_nums[1]}"
        with self._conn() as conn:
            row = conn.execute(
                "SELECT payout FROM race_payouts WHERE race_id=? AND bet_type='quinella' AND combination=?",
                (race_id, combination),
            ).fetchone()
        return row["payout"] if row else None

    def get_trio_payout(self, race_id: str, h1: int, h2: int, h3: int) -> float | None:
        """三連複払戻金を取得する。combination は馬番をソートした '小-中-大' 形式。"""
        sorted_nums = sorted([h1, h2, h3])
        combination = f"{sorted_nums[0]}-{sorted_nums[1]}-{sorted_nums[2]}"
        with self._conn() as conn:
            row = conn.execute(
                "SELECT payout FROM race_payouts WHERE race_id=? AND bet_type='trio' AND combination=?",
                (race_id, combination),
            ).fetchone()
        return row["payout"] if row else None

    def log_scrape(
        self, url: str, status_code: int, error_msg: str = None
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO scrape_log (url, scraped_at, status_code, error_msg)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(url) DO UPDATE SET
                       scraped_at = excluded.scraped_at,
                       status_code = excluded.status_code,
                       error_msg = excluded.error_msg""",
                (url, datetime.now().isoformat(), status_code, error_msg),
            )
