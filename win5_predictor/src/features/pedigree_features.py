"""血統特徴量 (~8個)

父系の馬場・距離別勝率
"""

import logging
from datetime import date
from typing import Any

logger = logging.getLogger(__name__)


def build_pedigree_features(
    sire_id: str,
    damsire_id: str,
    race_surface: str,
    race_distance: int,
    repo,
    before_date: date,
) -> dict[str, float]:
    """血統の特徴量を構築する"""
    f: dict[str, float] = {}

    # 父の成績
    sire_stats = _get_sire_stats(sire_id, before_date, repo)
    f["sire_win_rate"] = sire_stats.get("win_rate", 0.0)
    f["sire_top3_rate"] = sire_stats.get("top3_rate", 0.0)
    f["sire_runs"] = float(sire_stats.get("runs", 0))

    # 父×馬場別
    sire_surface_stats = _get_sire_surface_stats(
        sire_id, race_surface, before_date, repo
    )
    f["sire_surface_win_rate"] = sire_surface_stats.get("win_rate", 0.0)

    # 父×距離別
    sire_dist_stats = _get_sire_distance_stats(
        sire_id, race_distance, before_date, repo
    )
    f["sire_dist_win_rate"] = sire_dist_stats.get("win_rate", 0.0)

    # 母父の成績
    damsire_stats = _get_sire_stats(damsire_id, before_date, repo) if damsire_id else {}
    f["damsire_win_rate"] = damsire_stats.get("win_rate", 0.0)
    f["damsire_top3_rate"] = damsire_stats.get("top3_rate", 0.0)
    f["damsire_runs"] = float(damsire_stats.get("runs", 0))

    return f


def _get_sire_stats(
    sire_id: str, before_date: date, repo
) -> dict[str, Any]:
    """父の産駒成績を取得"""
    if not sire_id:
        return {"runs": 0, "wins": 0, "top3": 0, "win_rate": 0.0, "top3_rate": 0.0}

    with repo.db.cursor() as cur:
        row = cur.execute(
            """
            SELECT COUNT(*) as runs,
                   SUM(CASE WHEN rr.finish_position=1 THEN 1 ELSE 0 END) as wins,
                   SUM(CASE WHEN rr.finish_position<=3 THEN 1 ELSE 0 END) as top3
            FROM race_results rr
            JOIN races r ON rr.race_id = r.race_id
            JOIN horses h ON rr.horse_id = h.horse_id
            WHERE h.sire_id = ? AND r.race_date < ?
            """,
            (sire_id, before_date.isoformat()),
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


def _get_sire_surface_stats(
    sire_id: str, surface: str, before_date: date, repo
) -> dict[str, Any]:
    """父の馬場別産駒成績"""
    if not sire_id:
        return {"runs": 0, "win_rate": 0.0}

    with repo.db.cursor() as cur:
        row = cur.execute(
            """
            SELECT COUNT(*) as runs,
                   SUM(CASE WHEN rr.finish_position=1 THEN 1 ELSE 0 END) as wins
            FROM race_results rr
            JOIN races r ON rr.race_id = r.race_id
            JOIN horses h ON rr.horse_id = h.horse_id
            WHERE h.sire_id = ? AND r.surface = ? AND r.race_date < ?
            """,
            (sire_id, surface, before_date.isoformat()),
        ).fetchone()

    runs = row["runs"] or 0
    wins = row["wins"] or 0
    return {"runs": runs, "win_rate": wins / runs if runs > 0 else 0.0}


def _get_sire_distance_stats(
    sire_id: str, distance: int, before_date: date, repo
) -> dict[str, Any]:
    """父の距離別産駒成績(±200m範囲)"""
    if not sire_id:
        return {"runs": 0, "win_rate": 0.0}

    with repo.db.cursor() as cur:
        row = cur.execute(
            """
            SELECT COUNT(*) as runs,
                   SUM(CASE WHEN rr.finish_position=1 THEN 1 ELSE 0 END) as wins
            FROM race_results rr
            JOIN races r ON rr.race_id = r.race_id
            JOIN horses h ON rr.horse_id = h.horse_id
            WHERE h.sire_id = ? AND r.distance BETWEEN ? AND ?
                  AND r.race_date < ?
            """,
            (sire_id, distance - 200, distance + 200, before_date.isoformat()),
        ).fetchone()

    runs = row["runs"] or 0
    wins = row["wins"] or 0
    return {"runs": runs, "win_rate": wins / runs if runs > 0 else 0.0}
