"""騎手・調教師の特徴量 (~15個)"""

from datetime import date
from typing import Any


def build_jockey_features(
    jockey_stats: dict[str, Any],
    jockey_venue_stats: dict[str, Any],
    jockey_surface_stats: dict[str, Any],
    jockey_horse_combo: dict[str, Any],
) -> dict[str, float]:
    """騎手の特徴量を構築する"""
    f: dict[str, float] = {}

    # 全体成績
    f["j_win_rate"] = jockey_stats.get("win_rate", 0.0)
    f["j_top3_rate"] = jockey_stats.get("top3_rate", 0.0)
    f["j_runs"] = float(jockey_stats.get("runs", 0))

    # 競馬場別
    f["j_venue_win_rate"] = jockey_venue_stats.get("win_rate", 0.0)
    f["j_venue_top3_rate"] = jockey_venue_stats.get("top3_rate", 0.0)
    f["j_venue_runs"] = float(jockey_venue_stats.get("runs", 0))

    # 馬場別(芝/ダート)
    f["j_surface_win_rate"] = jockey_surface_stats.get("win_rate", 0.0)
    f["j_surface_runs"] = float(jockey_surface_stats.get("runs", 0))

    # 馬との相性(コンビ成績)
    f["j_combo_win_rate"] = jockey_horse_combo.get("win_rate", 0.0)
    f["j_combo_runs"] = float(jockey_horse_combo.get("runs", 0))

    return f


def build_trainer_features(
    trainer_stats: dict[str, Any],
    trainer_jockey_combo: dict[str, Any] | None = None,
) -> dict[str, float]:
    """調教師の特徴量を構築する"""
    f: dict[str, float] = {}

    # 全体成績
    f["t_win_rate"] = trainer_stats.get("win_rate", 0.0)
    f["t_top3_rate"] = trainer_stats.get("top3_rate", 0.0)
    f["t_runs"] = float(trainer_stats.get("runs", 0))

    # 騎手との相性
    if trainer_jockey_combo:
        f["tj_combo_win_rate"] = trainer_jockey_combo.get("win_rate", 0.0)
        f["tj_combo_runs"] = float(trainer_jockey_combo.get("runs", 0))
    else:
        f["tj_combo_win_rate"] = 0.0
        f["tj_combo_runs"] = 0.0

    return f


def get_jockey_horse_combo_stats(
    jockey_id: str,
    horse_id: str,
    before_date: date,
    repo,
) -> dict[str, Any]:
    """騎手×馬のコンビ成績を算出する"""
    from database.repository import Repository

    r: Repository = repo
    with r.db.cursor() as cur:
        row = cur.execute(
            """
            SELECT COUNT(*) as runs,
                   SUM(CASE WHEN rr.finish_position=1 THEN 1 ELSE 0 END) as wins,
                   SUM(CASE WHEN rr.finish_position<=3 THEN 1 ELSE 0 END) as top3
            FROM race_results rr
            JOIN races rc ON rr.race_id = rc.race_id
            WHERE rr.jockey_id = ? AND rr.horse_id = ? AND rc.race_date < ?
            """,
            (jockey_id, horse_id, before_date.isoformat()),
        ).fetchone()
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


def get_trainer_jockey_combo_stats(
    trainer_id: str,
    jockey_id: str,
    before_date: date,
    repo,
) -> dict[str, Any]:
    """調教師×騎手のコンビ成績を算出する"""
    from database.repository import Repository

    r: Repository = repo
    with r.db.cursor() as cur:
        row = cur.execute(
            """
            SELECT COUNT(*) as runs,
                   SUM(CASE WHEN rr.finish_position=1 THEN 1 ELSE 0 END) as wins,
                   SUM(CASE WHEN rr.finish_position<=3 THEN 1 ELSE 0 END) as top3
            FROM race_results rr
            JOIN races rc ON rr.race_id = rc.race_id
            WHERE rr.trainer_id = ? AND rr.jockey_id = ? AND rc.race_date < ?
            """,
            (trainer_id, jockey_id, before_date.isoformat()),
        ).fetchone()
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
