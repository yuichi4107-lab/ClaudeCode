"""レース・コース特徴量算出モジュール"""

from typing import Dict, List, Optional

from src.utils.constants import (
    DISTANCE_CATEGORIES,
    GRADE_MAPPING,
    TRACK_CONDITION_CODES,
    VENUE_NAME_TO_CODE,
)
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

# 回り方向コード
DIRECTION_CODES = {
    "右": 0,
    "左": 1,
    "直線": 2,
}

# 馬場種別コード
SURFACE_CODES = {
    "芝": 0,
    "ダート": 1,
    "障害": 2,
}


class RaceFeatureCalculator:
    """レース・コースに関する15特徴量を算出する"""

    def __init__(self, db_manager):
        self.db = db_manager

    @staticmethod
    def _get_distance_category_code(distance: Optional[int]) -> int:
        """距離区分を数値コードに変換する"""
        if distance is None:
            return 2  # middle default
        cats = list(DISTANCE_CATEGORIES.keys())
        for i, (cat, (low, high)) in enumerate(DISTANCE_CATEGORIES.items()):
            if low <= distance <= high:
                return i
        return 2

    def compute_post_position_bias(
        self,
        venue_code: str,
        distance: int,
        frame_number: int,
        before_date: str,
    ) -> float:
        """枠番別の歴史的勝率を算出する"""
        sql = """
            SELECT rr.finish_order
            FROM race_results rr
            JOIN races r ON rr.race_id = r.race_id
            WHERE r.venue_code = ?
              AND r.distance = ?
              AND rr.frame_number = ?
              AND r.race_date < ?
              AND rr.finish_order IS NOT NULL
        """
        with self.db._connect() as conn:
            rows = conn.execute(
                sql, (venue_code, distance, frame_number, before_date)
            ).fetchall()

        if not rows:
            return 0.0
        wins = sum(1 for r in rows if r["finish_order"] == 1)
        return wins / len(rows)

    def compute_features(
        self,
        race: Dict,
        result_row: Dict,
        before_date: str,
    ) -> Dict[str, Optional[float]]:
        """レース・コースの15特徴量を算出する。

        race: races テーブルの行
        result_row: race_results テーブルの行 (当該馬)
        """
        features: Dict[str, Optional[float]] = {}

        # --- 基本レース情報 ---
        features["horse_count"] = float(race.get("horse_count") or 0)
        features["distance"] = float(race.get("distance") or 0)
        features["distance_category"] = float(
            self._get_distance_category_code(race.get("distance"))
        )

        # 馬場種別
        race_type = race.get("race_type") or ""
        features["surface_type"] = float(SURFACE_CODES.get(race_type, 0))

        # 馬場状態
        track_cond = race.get("track_condition") or ""
        features["track_condition_code"] = float(
            TRACK_CONDITION_CODES.get(track_cond, 0)
        )

        # 競馬場コード
        venue_code = race.get("venue_code") or "00"
        try:
            features["venue_code"] = float(int(venue_code))
        except (ValueError, TypeError):
            features["venue_code"] = 0.0

        # 回り方向
        direction = race.get("direction") or ""
        features["direction_code"] = float(DIRECTION_CODES.get(direction, 0))

        # グレード
        grade = race.get("grade") or ""
        features["grade_code"] = float(GRADE_MAPPING.get(grade, 0))

        # 月
        race_date = race.get("race_date") or ""
        try:
            features["month"] = float(int(race_date.split("-")[1]))
        except (IndexError, ValueError, TypeError):
            features["month"] = 0.0

        # 重賞フラグ
        features["is_special_race"] = (
            1.0 if grade in ("G1", "G2", "G3") else 0.0
        )

        # --- 馬番・枠番 ---
        features["frame_number"] = float(result_row.get("frame_number") or 0)
        features["horse_number"] = float(result_row.get("horse_number") or 0)

        # --- 枠番バイアス ---
        frame = result_row.get("frame_number")
        dist = race.get("distance")
        if frame and dist and venue_code:
            features["post_position_bias"] = self.compute_post_position_bias(
                venue_code, dist, frame, before_date
            )
        else:
            features["post_position_bias"] = 0.0

        # --- field_quality (出走馬のスピード指数平均) はパイプラインで設定 ---
        features["field_quality"] = None

        return features
