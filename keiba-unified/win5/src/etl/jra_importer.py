"""jra DB（keiba_live.db）を読み、win5 Repository へ変換移植する"""

import logging
import sqlite3
from dataclasses import asdict
from datetime import date

from database.models import Horse, Jockey, Race, RaceResult, Trainer
from etl.normalize import (
    normalize_class,
    normalize_surface,
    split_sex_age,
    venue_code_from_race_id,
)

logger = logging.getLogger(__name__)


class JraImporter:
    """jra DB → win5 DB の一括/差分インポート（単一トランザクション・executemany）"""

    def __init__(self, jra_db_path, repository):
        self.jra_db_path = str(jra_db_path)
        self.repo = repository

    def _connect_jra(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.jra_db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _build_rows_horses(self, conn) -> list[tuple]:
        rows = []
        for row in conn.execute(
            "SELECT horse_id, name, sex, birth_year FROM horses"
        ):
            h = Horse(
                horse_id=row["horse_id"],
                horse_name=row["name"] or "",
                sex=row["sex"] or "",
                birth_year=row["birth_year"] or 0,
            )
            d = asdict(h)
            rows.append(tuple(d.values()))
        return rows

    def _build_rows_jockeys(self, conn) -> list[tuple]:
        rows = []
        for row in conn.execute("SELECT jockey_id, name FROM jockeys"):
            j = Jockey(jockey_id=row["jockey_id"], jockey_name=row["name"] or "")
            d = asdict(j)
            rows.append(tuple(d.values()))
        return rows

    def _build_rows_trainers(self, conn) -> list[tuple]:
        rows = []
        for row in conn.execute("SELECT trainer_id, name FROM trainers"):
            t = Trainer(trainer_id=row["trainer_id"], trainer_name=row["name"] or "")
            d = asdict(t)
            rows.append(tuple(d.values()))
        return rows

    def _build_rows_races(self, conn) -> list[tuple]:
        rows = []
        sql = (
            "SELECT race_id, date, venue, race_number, name, class, distance, "
            "surface, track_condition, weather, head_count FROM races"
        )
        for row in conn.execute(sql):
            cls_name, cls_code = normalize_class(row["class"] or "")
            r = Race(
                race_id=row["race_id"],
                race_date=date.fromisoformat(row["date"]),
                venue_code=venue_code_from_race_id(row["race_id"]),
                venue_name=row["venue"] or "",
                race_number=row["race_number"] or 0,
                race_name=row["name"] or "",
                surface=normalize_surface(row["surface"] or ""),
                distance=row["distance"] or 0,
                track_condition=row["track_condition"] or "",
                weather=row["weather"] or "",
                race_class=cls_name,
                race_class_code=cls_code,
                num_runners=row["head_count"] or 0,
            )
            d = asdict(r)
            # date → isoformat 変換（sqlite は TEXT保存）
            d["race_date"] = r.race_date.isoformat()
            rows.append(tuple(d.values()))
        return rows

    def _build_rows_results(self, conn) -> list[tuple]:
        horse_names = {
            row["horse_id"]: (row["name"] or "")
            for row in conn.execute("SELECT horse_id, name FROM horses")
        }
        jockey_names = {
            row["jockey_id"]: (row["name"] or "")
            for row in conn.execute("SELECT jockey_id, name FROM jockeys")
        }
        trainer_names = {
            row["trainer_id"]: (row["name"] or "")
            for row in conn.execute("SELECT trainer_id, name FROM trainers")
        }

        rows = []
        for row in conn.execute("SELECT * FROM results ORDER BY race_id"):
            sex, age = split_sex_age(row["sex_age"] or "")
            rr = RaceResult(
                race_id=row["race_id"],
                horse_id=row["horse_id"],
                horse_name=horse_names.get(row["horse_id"], ""),
                finish_position=row["finish_position"],
                post_position=row["post_position"] or 0,
                horse_number=row["horse_number"] or 0,
                sex=sex,
                age=age,
                weight_carried=row["weight_carried"] or 0.0,
                jockey_id=row["jockey_id"] or "",
                jockey_name=jockey_names.get(row["jockey_id"], ""),
                trainer_id=row["trainer_id"] or "",
                trainer_name=trainer_names.get(row["trainer_id"], ""),
                last_3f=row["last_3f"],
                horse_weight=row["horse_weight"],
                weight_change=row["weight_change"],
                odds=row["odds_win"],
                popularity=row["popularity"],
                margin=row["margin"] or "",
                corner_positions=row["passing"] or "",
                prize_money=row["prize"] or 0.0,
            )
            rows.append(tuple(asdict(rr).values()))
        return rows

    @staticmethod
    def _make_upsert_sql(table: str, fields: list[str], conflict_keys: list[str]) -> str:
        cols = ", ".join(fields)
        placeholders = ", ".join(["?"] * len(fields))
        update = ", ".join(
            f"{k}=excluded.{k}" for k in fields if k not in conflict_keys
        )
        conflict = ", ".join(conflict_keys)
        return (
            f"INSERT OR REPLACE INTO {table} ({cols}) VALUES ({placeholders})"
        )

    def run(self) -> dict:
        from dataclasses import fields as dc_fields

        jra_conn = self._connect_jra()
        try:
            # --- データ収集（JRAコネクション、読み取り専用）---
            horse_rows = self._build_rows_horses(jra_conn)
            jockey_rows = self._build_rows_jockeys(jra_conn)
            trainer_rows = self._build_rows_trainers(jra_conn)
            race_rows = self._build_rows_races(jra_conn)
            result_rows = self._build_rows_results(jra_conn)
        finally:
            jra_conn.close()

        # --- win5 DB へ単一コネクション・単一トランザクションで一括書き込み ---
        win5_conn = self.repo.db.get_connection()
        try:
            # Google Drive 上の fsync を回避する高速化プラグマ
            win5_conn.execute("PRAGMA synchronous = OFF")
            win5_conn.execute("PRAGMA journal_mode = MEMORY")

            # horses
            h_fields = [f.name for f in dc_fields(Horse)]
            win5_conn.executemany(
                f"INSERT OR REPLACE INTO horses ({', '.join(h_fields)}) "
                f"VALUES ({', '.join(['?']*len(h_fields))})",
                horse_rows,
            )

            # jockeys
            j_fields = [f.name for f in dc_fields(Jockey)]
            win5_conn.executemany(
                f"INSERT OR REPLACE INTO jockeys ({', '.join(j_fields)}) "
                f"VALUES ({', '.join(['?']*len(j_fields))})",
                jockey_rows,
            )

            # trainers
            t_fields = [f.name for f in dc_fields(Trainer)]
            win5_conn.executemany(
                f"INSERT OR REPLACE INTO trainers ({', '.join(t_fields)}) "
                f"VALUES ({', '.join(['?']*len(t_fields))})",
                trainer_rows,
            )

            # races
            r_fields = [f.name for f in dc_fields(Race)]
            win5_conn.executemany(
                f"INSERT OR REPLACE INTO races ({', '.join(r_fields)}) "
                f"VALUES ({', '.join(['?']*len(r_fields))})",
                race_rows,
            )

            # race_results
            rr_fields = [f.name for f in dc_fields(RaceResult)]
            win5_conn.executemany(
                f"INSERT OR REPLACE INTO race_results ({', '.join(rr_fields)}) "
                f"VALUES ({', '.join(['?']*len(rr_fields))})",
                result_rows,
            )

            win5_conn.commit()
        except Exception:
            win5_conn.rollback()
            raise
        finally:
            # :memory: 以外はコネクションを閉じる
            if self.repo.db.db_path != ":memory:":
                win5_conn.close()

        n_races = len(race_rows)
        n_results = len(result_rows)
        logger.info("Imported races=%d results=%d", n_races, n_results)
        return {"races": n_races, "results": n_results}
