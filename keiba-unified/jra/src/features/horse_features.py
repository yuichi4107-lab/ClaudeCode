"""馬固有の特徴量算出モジュール"""

import re
import statistics
from typing import Dict, List, Optional

from src.utils.constants import (
    DISTANCE_CATEGORIES,
    GRADE_MAPPING,
    SEX_CODES,
    TRACK_CONDITION_CODES,
    VENUE_NAME_TO_CODE,
)
from src.utils.date_utils import parse_date, days_between
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class HorseFeatureCalculator:
    """馬固有の25特徴量を算出する"""

    def __init__(self, db_manager):
        self.db = db_manager

    def _get_past_results(
        self, horse_id: str, before_date: str, limit: Optional[int] = None
    ) -> List[Dict]:
        """指定日前の出走履歴を取得する (race_results + races テーブルから)"""
        sql = """
            SELECT rr.*, r.race_date, r.venue_code, r.venue_name, r.distance,
                   r.race_type, r.track_condition, r.grade, r.direction
            FROM race_results rr
            JOIN races r ON rr.race_id = r.race_id
            WHERE rr.horse_id = ?
              AND r.race_date < ?
            ORDER BY r.race_date DESC
        """
        params: list = [horse_id, before_date]
        if limit:
            sql += " LIMIT ?"
            params.append(limit)

        with self.db._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _parse_sex_age(sex_age: Optional[str]) -> tuple:
        """性齢文字列をパースする。例: '牡3' -> ('牡', 3)"""
        if not sex_age:
            return (None, None)
        match = re.match(r"([牡牝セ])(\d+)", sex_age)
        if match:
            return (match.group(1), int(match.group(2)))
        return (None, None)

    @staticmethod
    def _get_distance_category(distance: int) -> str:
        """距離区分を返す"""
        for cat, (low, high) in DISTANCE_CATEGORIES.items():
            if low <= distance <= high:
                return cat
        return "middle"

    @staticmethod
    def _parse_corner_4th(corner_positions_str: Optional[str]) -> Optional[int]:
        """コーナー通過順位文字列から4コーナーの位置を取得する"""
        if not corner_positions_str:
            return None
        parts = re.split(r"[-,]", corner_positions_str.strip())
        positions = []
        for p in parts:
            match = re.match(r"(\d+)", p.strip())
            if match:
                positions.append(int(match.group(1)))
        if positions:
            return positions[-1]  # 最終コーナー
        return None

    def compute_features(
        self,
        horse_id: str,
        before_date: str,
        current_race: Optional[Dict] = None,
        current_result: Optional[Dict] = None,
    ) -> Dict[str, Optional[float]]:
        """馬固有の25特徴量を算出する。

        current_race: 対象レース情報 (races テーブルの行)
        current_result: 対象レースの出走情報 (race_results テーブルの行)
        """
        past = self._get_past_results(horse_id, before_date)
        total = len(past)

        features: Dict[str, Optional[float]] = {}

        # --- 勝率・連対率 (全期間) ---
        if total > 0:
            wins = sum(1 for r in past if r.get("finish_order") == 1)
            top3 = sum(1 for r in past if r.get("finish_order") is not None and r["finish_order"] <= 3)
            features["win_rate_all"] = wins / total
            features["top3_rate_all"] = top3 / total
        else:
            features["win_rate_all"] = 0.0
            features["top3_rate_all"] = 0.0

        # --- 勝率・連対率 (直近5走) ---
        recent5 = past[:5]
        if recent5:
            wins_r5 = sum(1 for r in recent5 if r.get("finish_order") == 1)
            top3_r5 = sum(1 for r in recent5 if r.get("finish_order") is not None and r["finish_order"] <= 3)
            features["win_rate_recent5"] = wins_r5 / len(recent5)
            features["top3_rate_recent5"] = top3_r5 / len(recent5)
        else:
            features["win_rate_recent5"] = 0.0
            features["top3_rate_recent5"] = 0.0

        # --- 平均着順 (直近5走) ---
        finish_positions = [
            r["finish_order"] for r in recent5
            if r.get("finish_order") is not None
        ]
        features["avg_finish_position"] = (
            sum(finish_positions) / len(finish_positions) if finish_positions else None
        )

        # --- 上がり3F (直近3走平均, 直近10走ベスト) ---
        final_3f_values = [
            r["final_3f"] for r in past[:10]
            if r.get("final_3f") is not None and r["final_3f"] > 0
        ]
        if final_3f_values:
            last3_3f = final_3f_values[:3]
            features["final_3f_avg"] = sum(last3_3f) / len(last3_3f)
            features["final_3f_best"] = min(final_3f_values)
        else:
            features["final_3f_avg"] = None
            features["final_3f_best"] = None

        # --- 馬体重・増減 ---
        if current_result and current_result.get("horse_weight") is not None:
            features["horse_weight"] = float(current_result["horse_weight"])
            features["weight_change"] = (
                float(current_result["weight_change"])
                if current_result.get("weight_change") is not None
                else 0.0
            )
        elif past and past[0].get("horse_weight") is not None:
            features["horse_weight"] = float(past[0]["horse_weight"])
            features["weight_change"] = 0.0
        else:
            features["horse_weight"] = None
            features["weight_change"] = None

        # --- 前走からの間隔日数 ---
        if past:
            try:
                features["days_since_last_race"] = float(
                    days_between(past[0]["race_date"], before_date)
                )
            except (ValueError, TypeError):
                features["days_since_last_race"] = None
        else:
            features["days_since_last_race"] = None

        # --- 年齢・性別 ---
        sex_age_str = None
        if current_result and current_result.get("sex_age"):
            sex_age_str = current_result["sex_age"]
        elif past and past[0].get("sex_age"):
            sex_age_str = past[0]["sex_age"]

        sex_char, age = self._parse_sex_age(sex_age_str)
        features["age"] = float(age) if age is not None else None
        features["sex_code"] = float(SEX_CODES.get(sex_char, 0)) if sex_char else None

        # --- 出走数 ---
        features["career_races"] = float(total)

        # --- 距離適性 (該当距離区分の勝利数) ---
        target_distance = None
        if current_race and current_race.get("distance"):
            target_distance = current_race["distance"]
        if target_distance:
            target_cat = self._get_distance_category(target_distance)
            features["distance_wins"] = float(sum(
                1 for r in past
                if r.get("finish_order") == 1
                and r.get("distance") is not None
                and self._get_distance_category(r["distance"]) == target_cat
            ))
        else:
            features["distance_wins"] = 0.0

        # --- 馬場適性 (該当馬場での勝利数) ---
        target_surface = None
        if current_race and current_race.get("race_type"):
            target_surface = current_race["race_type"]
        if target_surface:
            features["surface_wins"] = float(sum(
                1 for r in past
                if r.get("finish_order") == 1 and r.get("race_type") == target_surface
            ))
        else:
            features["surface_wins"] = 0.0

        # --- 競馬場適性 (該当場での勝利数) ---
        target_venue = None
        if current_race and current_race.get("venue_code"):
            target_venue = current_race["venue_code"]
        if target_venue:
            features["venue_wins"] = float(sum(
                1 for r in past
                if r.get("finish_order") == 1 and r.get("venue_code") == target_venue
            ))
        else:
            features["venue_wins"] = 0.0

        # --- 馬場状態別成績 ---
        target_condition = None
        if current_race and current_race.get("track_condition"):
            target_condition = current_race["track_condition"]
        if target_condition:
            cond_races = [
                r for r in past if r.get("track_condition") == target_condition
            ]
            if cond_races:
                cond_top3 = sum(
                    1 for r in cond_races
                    if r.get("finish_order") is not None and r["finish_order"] <= 3
                )
                features["condition_perf"] = cond_top3 / len(cond_races)
            else:
                features["condition_perf"] = 0.0
        else:
            features["condition_perf"] = 0.0

        # --- クラスレベル ---
        target_grade = None
        if current_race and current_race.get("grade"):
            target_grade = current_race["grade"]
        features["class_level"] = float(GRADE_MAPPING.get(target_grade, 0)) if target_grade else 0.0

        # --- コーナー通過順位平均 (直近3走, 最終コーナー) ---
        corner_positions_4th = []
        for r in past[:3]:
            pos = self._parse_corner_4th(r.get("corner_positions"))
            if pos is not None:
                corner_positions_4th.append(pos)
        features["corner_position_avg"] = (
            sum(corner_positions_4th) / len(corner_positions_4th)
            if corner_positions_4th
            else None
        )

        # --- 斤量差 (基準55kgとの差) ---
        if current_result and current_result.get("weight_carry") is not None:
            features["weight_carry_diff"] = float(current_result["weight_carry"]) - 55.0
        elif past and past[0].get("weight_carry") is not None:
            features["weight_carry_diff"] = float(past[0]["weight_carry"]) - 55.0
        else:
            features["weight_carry_diff"] = 0.0

        # --- トラック替わり特徴量 ---
        features.update(
            self._compute_track_switch_features(past, current_race)
        )

        return features

    @staticmethod
    def _compute_track_switch_features(
        past: List[Dict], current_race: Optional[Dict]
    ) -> Dict[str, Optional[float]]:
        """トラック替わり特徴量 (5特徴量)"""
        cur_surface = current_race.get("race_type") if current_race else None
        defaults = {
            "is_first_dirt": 0.0,
            "is_first_turf": 0.0,
            "career_at_switch": 0.0,
            "prev_surface_runs": 0.0,
            "prev_weight_for_switch": 0.0,
        }
        if not past or not cur_surface:
            return defaults

        past_surfaces = [
            r["race_type"] for r in past
            if r.get("race_type") and r["race_type"] in ("芝", "ダート")
        ]
        if not past_surfaces:
            return defaults

        features = dict(defaults)

        if cur_surface == "ダート" and "ダート" not in past_surfaces:
            features["is_first_dirt"] = 1.0
            features["career_at_switch"] = float(len(past_surfaces))
        elif cur_surface == "芝" and "芝" not in past_surfaces:
            features["is_first_turf"] = 1.0
            features["career_at_switch"] = float(len(past_surfaces))

        # 前の馬場での連続出走数
        prev_surface = past_surfaces[0]
        streak = 0
        for s in past_surfaces:
            if s == prev_surface:
                streak += 1
            else:
                break
        features["prev_surface_runs"] = float(streak)

        # 前走の馬体重
        for r in past:
            hw = r.get("horse_weight")
            if hw and hw > 0:
                features["prev_weight_for_switch"] = float(hw)
                break

        return features
