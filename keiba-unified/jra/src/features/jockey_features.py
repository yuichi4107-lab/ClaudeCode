"""騎手特徴量算出モジュール"""

import statistics
from datetime import timedelta
from typing import Dict, List, Optional

from src.utils.date_utils import parse_date
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class JockeyFeatureCalculator:
    """騎手に関する10特徴量を算出する"""

    def __init__(self, db_manager):
        self.db = db_manager

    def _get_jockey_results_1y(
        self, jockey_id: str, before_date: str
    ) -> List[Dict]:
        """対象日の1年前から対象日前日までの騎手成績を取得する"""
        dt = parse_date(before_date)
        start_dt = dt - timedelta(days=365)
        start_date = start_dt.strftime("%Y-%m-%d")

        sql = """
            SELECT rr.*, r.race_date, r.venue_code, r.distance,
                   r.race_type, r.track_condition
            FROM race_results rr
            JOIN races r ON rr.race_id = r.race_id
            WHERE rr.jockey_id = ?
              AND r.race_date >= ?
              AND r.race_date < ?
            ORDER BY r.race_date DESC
        """
        with self.db._connect() as conn:
            rows = conn.execute(sql, (jockey_id, start_date, before_date)).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _get_distance_category(distance: Optional[int]) -> str:
        """距離区分を返す"""
        if distance is None:
            return "middle"
        from src.utils.constants import DISTANCE_CATEGORIES
        for cat, (low, high) in DISTANCE_CATEGORIES.items():
            if low <= distance <= high:
                return cat
        return "middle"

    def compute_features(
        self,
        jockey_id: str,
        horse_id: str,
        trainer_id: str,
        before_date: str,
        venue_code: Optional[str] = None,
        surface_type: Optional[str] = None,
        distance: Optional[int] = None,
        weight_carry: Optional[float] = None,
    ) -> Dict[str, Optional[float]]:
        """騎手に関する10特徴量を算出する。"""
        results = self._get_jockey_results_1y(jockey_id, before_date)
        total = len(results)

        features: Dict[str, Optional[float]] = {}

        # --- 勝率・3着内率 (1年間) ---
        if total > 0:
            wins = sum(1 for r in results if r.get("finish_order") == 1)
            top3 = sum(
                1 for r in results
                if r.get("finish_order") is not None and r["finish_order"] <= 3
            )
            features["jockey_win_rate_1y"] = wins / total
            features["jockey_top3_rate_1y"] = top3 / total
        else:
            features["jockey_win_rate_1y"] = 0.0
            features["jockey_top3_rate_1y"] = 0.0

        # --- 競馬場別勝率 ---
        if venue_code and total > 0:
            venue_results = [r for r in results if r.get("venue_code") == venue_code]
            if venue_results:
                venue_wins = sum(1 for r in venue_results if r.get("finish_order") == 1)
                features["jockey_venue_rate"] = venue_wins / len(venue_results)
            else:
                features["jockey_venue_rate"] = 0.0
        else:
            features["jockey_venue_rate"] = 0.0

        # --- 馬場別勝率 ---
        if surface_type and total > 0:
            surface_results = [r for r in results if r.get("race_type") == surface_type]
            if surface_results:
                surface_wins = sum(1 for r in surface_results if r.get("finish_order") == 1)
                features["jockey_surface_rate"] = surface_wins / len(surface_results)
            else:
                features["jockey_surface_rate"] = 0.0
        else:
            features["jockey_surface_rate"] = 0.0

        # --- 距離別勝率 ---
        if distance and total > 0:
            target_cat = self._get_distance_category(distance)
            dist_results = [
                r for r in results
                if self._get_distance_category(r.get("distance")) == target_cat
            ]
            if dist_results:
                dist_wins = sum(1 for r in dist_results if r.get("finish_order") == 1)
                features["jockey_distance_rate"] = dist_wins / len(dist_results)
            else:
                features["jockey_distance_rate"] = 0.0
        else:
            features["jockey_distance_rate"] = 0.0

        # --- 騎手×調教師コンビ成績 ---
        if trainer_id and total > 0:
            combo_results = [r for r in results if r.get("trainer_id") == trainer_id]
            if combo_results:
                combo_top3 = sum(
                    1 for r in combo_results
                    if r.get("finish_order") is not None and r["finish_order"] <= 3
                )
                features["jockey_trainer_combo"] = combo_top3 / len(combo_results)
            else:
                features["jockey_trainer_combo"] = 0.0
        else:
            features["jockey_trainer_combo"] = 0.0

        # --- 騎手×馬コンビ成績 ---
        if horse_id and total > 0:
            horse_results = [r for r in results if r.get("horse_id") == horse_id]
            if horse_results:
                horse_top3 = sum(
                    1 for r in horse_results
                    if r.get("finish_order") is not None and r["finish_order"] <= 3
                )
                features["jockey_horse_combo"] = horse_top3 / len(horse_results)
            else:
                features["jockey_horse_combo"] = 0.0
        else:
            features["jockey_horse_combo"] = 0.0

        # --- 勝利時の平均オッズ ---
        winning_odds = [
            r["odds"] for r in results
            if r.get("finish_order") == 1 and r.get("odds") is not None and r["odds"] > 0
        ]
        features["jockey_avg_odds_win"] = (
            sum(winning_odds) / len(winning_odds) if winning_odds else None
        )

        # --- 騎手乗り替わりフラグ ---
        features["jockey_change_flag"] = self._compute_jockey_change(
            horse_id, jockey_id, before_date
        )

        # --- 騎手の斤量レンジ内フラグ ---
        if weight_carry is not None and total > 0:
            carry_values = [
                r["weight_carry"] for r in results
                if r.get("weight_carry") is not None
            ]
            if carry_values:
                avg_carry = sum(carry_values) / len(carry_values)
                std_carry = (
                    statistics.stdev(carry_values) if len(carry_values) >= 2 else 1.0
                )
                if std_carry == 0:
                    std_carry = 1.0
                features["jockey_weight_range"] = (
                    1.0 if abs(weight_carry - avg_carry) <= std_carry else 0.0
                )
            else:
                features["jockey_weight_range"] = 1.0
        else:
            features["jockey_weight_range"] = 1.0

        return features

    def _compute_jockey_change(
        self, horse_id: str, current_jockey_id: str, before_date: str
    ) -> float:
        """前走と騎手が変わったかどうかを返す (1=変更, 0=同じ)"""
        sql = """
            SELECT rr.jockey_id
            FROM race_results rr
            JOIN races r ON rr.race_id = r.race_id
            WHERE rr.horse_id = ?
              AND r.race_date < ?
            ORDER BY r.race_date DESC
            LIMIT 1
        """
        with self.db._connect() as conn:
            row = conn.execute(sql, (horse_id, before_date)).fetchone()

        if row is None:
            return 0.0  # 初出走
        return 1.0 if row["jockey_id"] != current_jockey_id else 0.0
