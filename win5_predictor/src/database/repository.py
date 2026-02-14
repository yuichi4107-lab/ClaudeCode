"""CRUD操作リポジトリ"""

import json
import logging
from dataclasses import asdict
from datetime import date
from typing import Any

import pandas as pd

from database.connection import Database, db
from database.models import (
    Horse,
    Jockey,
    ModelInfo,
    Race,
    RaceResult,
    Trainer,
    Win5Bet,
    Win5Event,
)

logger = logging.getLogger(__name__)


class Repository:
    """データベースCRUD操作"""

    def __init__(self, database: Database | None = None):
        self.db = database or db

    # ──────────────────────────────────
    # Race
    # ──────────────────────────────────
    def upsert_race(self, race: Race) -> None:
        d = asdict(race)
        cols = ", ".join(d.keys())
        placeholders = ", ".join(["?"] * len(d))
        update = ", ".join(f"{k}=excluded.{k}" for k in d if k != "race_id")
        sql = (
            f"INSERT INTO races ({cols}) VALUES ({placeholders}) "
            f"ON CONFLICT(race_id) DO UPDATE SET {update}, "
            f"updated_at=CURRENT_TIMESTAMP"
        )
        with self.db.cursor() as cur:
            cur.execute(sql, list(d.values()))

    def get_race(self, race_id: str) -> Race | None:
        with self.db.cursor() as cur:
            row = cur.execute(
                "SELECT * FROM races WHERE race_id=?", (race_id,)
            ).fetchone()
        if row is None:
            return None
        return Race(**{k: row[k] for k in Race.__dataclass_fields__})

    def get_races_by_date(self, race_date: date) -> list[Race]:
        with self.db.cursor() as cur:
            rows = cur.execute(
                "SELECT * FROM races WHERE race_date=? ORDER BY venue_code, race_number",
                (race_date.isoformat(),),
            ).fetchall()
        return [
            Race(**{k: row[k] for k in Race.__dataclass_fields__}) for row in rows
        ]

    def get_races_in_range(self, start: date, end: date) -> pd.DataFrame:
        with self.db.cursor() as cur:
            rows = cur.execute(
                "SELECT * FROM races WHERE race_date BETWEEN ? AND ? ORDER BY race_date, venue_code, race_number",
                (start.isoformat(), end.isoformat()),
            ).fetchall()
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame([dict(r) for r in rows])

    # ──────────────────────────────────
    # RaceResult
    # ──────────────────────────────────
    def upsert_race_result(self, result: RaceResult) -> None:
        d = asdict(result)
        cols = ", ".join(d.keys())
        placeholders = ", ".join(["?"] * len(d))
        update = ", ".join(
            f"{k}=excluded.{k}" for k in d if k not in ("race_id", "horse_number")
        )
        sql = (
            f"INSERT INTO race_results ({cols}) VALUES ({placeholders}) "
            f"ON CONFLICT(race_id, horse_number) DO UPDATE SET {update}"
        )
        with self.db.cursor() as cur:
            cur.execute(sql, list(d.values()))

    def bulk_upsert_race_results(self, results: list[RaceResult]) -> None:
        if not results:
            return
        with self.db.transaction() as conn:
            for result in results:
                d = asdict(result)
                cols = ", ".join(d.keys())
                placeholders = ", ".join(["?"] * len(d))
                update = ", ".join(
                    f"{k}=excluded.{k}"
                    for k in d
                    if k not in ("race_id", "horse_number")
                )
                sql = (
                    f"INSERT INTO race_results ({cols}) VALUES ({placeholders}) "
                    f"ON CONFLICT(race_id, horse_number) DO UPDATE SET {update}"
                )
                conn.execute(sql, list(d.values()))

    def get_race_results(self, race_id: str) -> list[RaceResult]:
        with self.db.cursor() as cur:
            rows = cur.execute(
                "SELECT * FROM race_results WHERE race_id=? ORDER BY finish_position",
                (race_id,),
            ).fetchall()
        return [
            RaceResult(**{k: row[k] for k in RaceResult.__dataclass_fields__})
            for row in rows
        ]

    def get_horse_history(
        self, horse_id: str, before_date: date | None = None, limit: int = 10
    ) -> pd.DataFrame:
        sql = """
            SELECT rr.*, r.race_date, r.venue_code, r.venue_name, r.surface,
                   r.distance, r.track_condition, r.race_class, r.race_class_code,
                   r.num_runners
            FROM race_results rr
            JOIN races r ON rr.race_id = r.race_id
            WHERE rr.horse_id = ?
        """
        params: list[Any] = [horse_id]
        if before_date:
            sql += " AND r.race_date < ?"
            params.append(before_date.isoformat())
        sql += " ORDER BY r.race_date DESC LIMIT ?"
        params.append(limit)

        with self.db.cursor() as cur:
            rows = cur.execute(sql, params).fetchall()
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame([dict(r) for r in rows])

    def get_results_in_range(self, start: date, end: date) -> pd.DataFrame:
        sql = """
            SELECT rr.*, r.race_date, r.venue_code, r.venue_name, r.surface,
                   r.distance, r.track_condition, r.race_class, r.race_class_code,
                   r.num_runners, r.weight_rule
            FROM race_results rr
            JOIN races r ON rr.race_id = r.race_id
            WHERE r.race_date BETWEEN ? AND ?
            ORDER BY r.race_date, r.venue_code, r.race_number, rr.horse_number
        """
        with self.db.cursor() as cur:
            rows = cur.execute(sql, (start.isoformat(), end.isoformat())).fetchall()
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame([dict(r) for r in rows])

    # ──────────────────────────────────
    # Horse
    # ──────────────────────────────────
    def upsert_horse(self, horse: Horse) -> None:
        d = asdict(horse)
        cols = ", ".join(d.keys())
        placeholders = ", ".join(["?"] * len(d))
        update = ", ".join(f"{k}=excluded.{k}" for k in d if k != "horse_id")
        sql = (
            f"INSERT INTO horses ({cols}) VALUES ({placeholders}) "
            f"ON CONFLICT(horse_id) DO UPDATE SET {update}, "
            f"updated_at=CURRENT_TIMESTAMP"
        )
        with self.db.cursor() as cur:
            cur.execute(sql, list(d.values()))

    def get_horse(self, horse_id: str) -> Horse | None:
        with self.db.cursor() as cur:
            row = cur.execute(
                "SELECT * FROM horses WHERE horse_id=?", (horse_id,)
            ).fetchone()
        if row is None:
            return None
        return Horse(**{k: row[k] for k in Horse.__dataclass_fields__})

    # ──────────────────────────────────
    # Jockey / Trainer
    # ──────────────────────────────────
    def upsert_jockey(self, jockey: Jockey) -> None:
        d = asdict(jockey)
        cols = ", ".join(d.keys())
        placeholders = ", ".join(["?"] * len(d))
        update = ", ".join(f"{k}=excluded.{k}" for k in d if k != "jockey_id")
        sql = (
            f"INSERT INTO jockeys ({cols}) VALUES ({placeholders}) "
            f"ON CONFLICT(jockey_id) DO UPDATE SET {update}, "
            f"updated_at=CURRENT_TIMESTAMP"
        )
        with self.db.cursor() as cur:
            cur.execute(sql, list(d.values()))

    def upsert_trainer(self, trainer: Trainer) -> None:
        d = asdict(trainer)
        cols = ", ".join(d.keys())
        placeholders = ", ".join(["?"] * len(d))
        update = ", ".join(f"{k}=excluded.{k}" for k in d if k != "trainer_id")
        sql = (
            f"INSERT INTO trainers ({cols}) VALUES ({placeholders}) "
            f"ON CONFLICT(trainer_id) DO UPDATE SET {update}, "
            f"updated_at=CURRENT_TIMESTAMP"
        )
        with self.db.cursor() as cur:
            cur.execute(sql, list(d.values()))

    def get_jockey_stats(
        self,
        jockey_id: str,
        before_date: date | None = None,
        venue_code: str | None = None,
        surface: str | None = None,
    ) -> dict[str, Any]:
        sql = """
            SELECT COUNT(*) as runs,
                   SUM(CASE WHEN rr.finish_position=1 THEN 1 ELSE 0 END) as wins,
                   SUM(CASE WHEN rr.finish_position<=3 THEN 1 ELSE 0 END) as top3
            FROM race_results rr
            JOIN races r ON rr.race_id = r.race_id
            WHERE rr.jockey_id = ?
        """
        params: list[Any] = [jockey_id]
        if before_date:
            sql += " AND r.race_date < ?"
            params.append(before_date.isoformat())
        if venue_code:
            sql += " AND r.venue_code = ?"
            params.append(venue_code)
        if surface:
            sql += " AND r.surface = ?"
            params.append(surface)

        with self.db.cursor() as cur:
            row = cur.execute(sql, params).fetchone()
        runs = row["runs"] or 0
        wins = row["wins"] or 0
        top3 = row["top3"] or 0
        return {
            "runs": runs,
            "wins": wins,
            "top3": top3,
            "win_rate": wins / runs if runs > 0 else 0.0,
            "top3_rate": top3 / runs if runs > 0 else 0.0,
        }

    def get_trainer_stats(
        self, trainer_id: str, before_date: date | None = None
    ) -> dict[str, Any]:
        sql = """
            SELECT COUNT(*) as runs,
                   SUM(CASE WHEN rr.finish_position=1 THEN 1 ELSE 0 END) as wins,
                   SUM(CASE WHEN rr.finish_position<=3 THEN 1 ELSE 0 END) as top3
            FROM race_results rr
            JOIN races r ON rr.race_id = r.race_id
            WHERE rr.trainer_id = ?
        """
        params: list[Any] = [trainer_id]
        if before_date:
            sql += " AND r.race_date < ?"
            params.append(before_date.isoformat())

        with self.db.cursor() as cur:
            row = cur.execute(sql, params).fetchone()
        runs = row["runs"] or 0
        wins = row["wins"] or 0
        top3 = row["top3"] or 0
        return {
            "runs": runs,
            "wins": wins,
            "top3": top3,
            "win_rate": wins / runs if runs > 0 else 0.0,
            "top3_rate": top3 / runs if runs > 0 else 0.0,
        }

    # ──────────────────────────────────
    # Win5
    # ──────────────────────────────────
    def upsert_win5_event(self, event: Win5Event) -> None:
        d = asdict(event)
        cols = ", ".join(d.keys())
        placeholders = ", ".join(["?"] * len(d))
        update = ", ".join(f"{k}=excluded.{k}" for k in d if k != "event_id")
        sql = (
            f"INSERT INTO win5_events ({cols}) VALUES ({placeholders}) "
            f"ON CONFLICT(event_id) DO UPDATE SET {update}"
        )
        with self.db.cursor() as cur:
            cur.execute(sql, list(d.values()))

    def get_win5_event(self, event_id: str) -> Win5Event | None:
        with self.db.cursor() as cur:
            row = cur.execute(
                "SELECT * FROM win5_events WHERE event_id=?", (event_id,)
            ).fetchone()
        if row is None:
            return None
        return Win5Event(**{k: row[k] for k in Win5Event.__dataclass_fields__})

    def get_win5_events_in_range(self, start: date, end: date) -> list[Win5Event]:
        with self.db.cursor() as cur:
            rows = cur.execute(
                "SELECT * FROM win5_events WHERE event_date BETWEEN ? AND ? "
                "ORDER BY event_date",
                (start.isoformat(), end.isoformat()),
            ).fetchall()
        return [
            Win5Event(**{k: row[k] for k in Win5Event.__dataclass_fields__})
            for row in rows
        ]

    def save_win5_bet(self, bet: Win5Bet) -> int:
        d = asdict(bet)
        cols = ", ".join(d.keys())
        placeholders = ", ".join(["?"] * len(d))
        sql = f"INSERT INTO win5_bets ({cols}) VALUES ({placeholders})"
        with self.db.cursor() as cur:
            cur.execute(sql, list(d.values()))
            return cur.lastrowid

    # ──────────────────────────────────
    # Bankroll
    # ──────────────────────────────────
    def record_bankroll(
        self,
        record_date: date,
        balance: float,
        deposit: float = 0,
        withdrawal: float = 0,
        bet_amount: float = 0,
        payout: float = 0,
        note: str = "",
    ) -> None:
        with self.db.cursor() as cur:
            cur.execute(
                "INSERT INTO bankroll (record_date, balance, deposit, withdrawal, "
                "bet_amount, payout, note) VALUES (?,?,?,?,?,?,?)",
                (record_date.isoformat(), balance, deposit, withdrawal, bet_amount, payout, note),
            )

    def get_bankroll_history(self) -> pd.DataFrame:
        with self.db.cursor() as cur:
            rows = cur.execute(
                "SELECT * FROM bankroll ORDER BY record_date"
            ).fetchall()
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame([dict(r) for r in rows])

    # ──────────────────────────────────
    # Model Registry
    # ──────────────────────────────────
    def register_model(self, model: ModelInfo) -> None:
        d = asdict(model)
        if d.get("train_start"):
            d["train_start"] = d["train_start"].isoformat() if isinstance(d["train_start"], date) else d["train_start"]
        if d.get("train_end"):
            d["train_end"] = d["train_end"].isoformat() if isinstance(d["train_end"], date) else d["train_end"]
        cols = ", ".join(d.keys())
        placeholders = ", ".join(["?"] * len(d))
        update = ", ".join(f"{k}=excluded.{k}" for k in d if k != "model_id")
        sql = (
            f"INSERT INTO model_registry ({cols}) VALUES ({placeholders}) "
            f"ON CONFLICT(model_id) DO UPDATE SET {update}"
        )
        with self.db.cursor() as cur:
            cur.execute(sql, list(d.values()))

    def get_active_model(self) -> ModelInfo | None:
        with self.db.cursor() as cur:
            row = cur.execute(
                "SELECT * FROM model_registry WHERE is_active=1 "
                "ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        return ModelInfo(**{k: row[k] for k in ModelInfo.__dataclass_fields__})

    def set_active_model(self, model_id: str) -> None:
        with self.db.transaction() as conn:
            conn.execute("UPDATE model_registry SET is_active=0")
            conn.execute(
                "UPDATE model_registry SET is_active=1 WHERE model_id=?",
                (model_id,),
            )

    # ──────────────────────────────────
    # Feature Cache
    # ──────────────────────────────────
    def cache_features(
        self, race_id: str, horse_id: str, features: dict
    ) -> None:
        cache_key = f"{race_id}_{horse_id}"
        with self.db.cursor() as cur:
            cur.execute(
                "INSERT OR REPLACE INTO feature_cache "
                "(cache_key, race_id, horse_id, features) VALUES (?,?,?,?)",
                (cache_key, race_id, horse_id, json.dumps(features)),
            )

    def get_cached_features(self, race_id: str, horse_id: str) -> dict | None:
        cache_key = f"{race_id}_{horse_id}"
        with self.db.cursor() as cur:
            row = cur.execute(
                "SELECT features FROM feature_cache WHERE cache_key=?",
                (cache_key,),
            ).fetchone()
        if row is None:
            return None
        return json.loads(row["features"])

    # ──────────────────────────────────
    # Odds History
    # ──────────────────────────────────
    def save_odds(
        self,
        race_id: str,
        horse_number: int,
        timestamp: str,
        win_odds: float,
        place_odds_min: float | None = None,
        place_odds_max: float | None = None,
    ) -> None:
        with self.db.cursor() as cur:
            cur.execute(
                "INSERT OR REPLACE INTO odds_history "
                "(race_id, horse_number, timestamp, win_odds, place_odds_min, place_odds_max) "
                "VALUES (?,?,?,?,?,?)",
                (race_id, horse_number, timestamp, win_odds, place_odds_min, place_odds_max),
            )

    # ──────────────────────────────────
    # 汎用
    # ──────────────────────────────────
    def count_races(self) -> int:
        with self.db.cursor() as cur:
            row = cur.execute("SELECT COUNT(*) as cnt FROM races").fetchone()
        return row["cnt"]

    def count_results(self) -> int:
        with self.db.cursor() as cur:
            row = cur.execute("SELECT COUNT(*) as cnt FROM race_results").fetchone()
        return row["cnt"]

    def get_date_range(self) -> tuple[str, str] | None:
        with self.db.cursor() as cur:
            row = cur.execute(
                "SELECT MIN(race_date) as min_d, MAX(race_date) as max_d FROM races"
            ).fetchone()
        if row["min_d"] is None:
            return None
        return (row["min_d"], row["max_d"])
