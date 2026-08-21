"""スピード指数算出モジュール"""

import statistics
from typing import Dict, List, Optional

from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class SpeedIndexCalculator:
    """走破タイムからスピード指数を算出する"""

    def __init__(self, db_manager):
        self.db = db_manager

    def compute_base_time(
        self,
        venue_code: str,
        distance: int,
        surface_type: str,
        track_condition: str,
        before_date: str,
        lookback_years: int = 3,
    ) -> Optional[float]:
        """同条件の過去N年間の走破タイム中央値を算出する。

        before_dateより前のデータのみ使用する。
        """
        from src.utils.date_utils import parse_date
        from datetime import timedelta

        cutoff_dt = parse_date(before_date)
        start_dt = cutoff_dt - timedelta(days=lookback_years * 365)
        start_date = start_dt.strftime("%Y-%m-%d")

        sql = """
            SELECT rr.finish_time
            FROM race_results rr
            JOIN races r ON rr.race_id = r.race_id
            WHERE r.venue_code = ?
              AND r.distance = ?
              AND r.race_type = ?
              AND r.track_condition = ?
              AND r.race_date >= ?
              AND r.race_date < ?
              AND rr.finish_time IS NOT NULL
              AND rr.finish_time > 0
              AND rr.finish_order IS NOT NULL
              AND rr.finish_order <= 5
        """
        params = (venue_code, distance, surface_type, track_condition,
                  start_date, before_date)

        with self.db._connect() as conn:
            rows = conn.execute(sql, params).fetchall()

        times = [row["finish_time"] for row in rows]
        if not times:
            return None
        return statistics.median(times)

    def compute_speed_index(
        self,
        finish_time: float,
        base_time: float,
        weight_carry: float,
        distance: int,
    ) -> float:
        """スピード指数を算出する。

        speed_index = (base_time - finish_time) / base_time * 1000 + weight_correction
        weight_correction = (weight_carry - 55) * 2
        """
        if base_time <= 0 or finish_time <= 0:
            return 0.0
        time_component = (base_time - finish_time) / base_time * 1000
        weight_correction = (weight_carry - 55.0) * 2.0
        return time_component + weight_correction

    def get_horse_speed_indices(
        self, horse_id: str, before_date: str, n_races: int = 10
    ) -> List[float]:
        """指定日前の直近nレースのスピード指数を取得する。"""
        sql = """
            SELECT rr.finish_time, rr.weight_carry, r.venue_code,
                   r.distance, r.race_type, r.track_condition, r.race_date
            FROM race_results rr
            JOIN races r ON rr.race_id = r.race_id
            WHERE rr.horse_id = ?
              AND r.race_date < ?
              AND rr.finish_time IS NOT NULL
              AND rr.finish_time > 0
            ORDER BY r.race_date DESC
            LIMIT ?
        """
        with self.db._connect() as conn:
            rows = conn.execute(sql, (horse_id, before_date, n_races)).fetchall()

        indices = []
        for row in rows:
            base_time = self.compute_base_time(
                row["venue_code"],
                row["distance"],
                row["race_type"],
                row["track_condition"],
                row["race_date"],
            )
            if base_time is None:
                continue
            si = self.compute_speed_index(
                row["finish_time"],
                base_time,
                row["weight_carry"],
                row["distance"],
            )
            indices.append(si)
        return indices

    def compute_features(self, horse_id: str, before_date: str) -> Dict[str, Optional[float]]:
        """スピード指数に関する特徴量を算出する。

        Returns:
            speed_index_last3: 直近3レースの平均スピード指数
            speed_index_best3: 直近10レース中ベスト3の平均
            speed_index_std: 直近5レースの標準偏差
        """
        indices = self.get_horse_speed_indices(horse_id, before_date, n_races=10)

        result: Dict[str, Optional[float]] = {
            "speed_index_last3": None,
            "speed_index_best3": None,
            "speed_index_std": None,
        }

        if len(indices) >= 1:
            last3 = indices[:3]
            result["speed_index_last3"] = sum(last3) / len(last3)

            sorted_desc = sorted(indices, reverse=True)
            best3 = sorted_desc[:3]
            result["speed_index_best3"] = sum(best3) / len(best3)

        if len(indices) >= 2:
            last5 = indices[:5]
            result["speed_index_std"] = statistics.stdev(last5) if len(last5) >= 2 else 0.0

        return result
