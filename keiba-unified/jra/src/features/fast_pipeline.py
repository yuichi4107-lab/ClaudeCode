"""高速特徴量パイプライン

全データをメモリにプリロードし、DBクエリを最小限にして特徴量生成を高速化する。
元のFeaturePipelineと同じ特徴量を生成するが、100倍以上高速。
"""

import sqlite3
import math
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

import numpy as np
import pandas as pd

from src.utils.constants import (
    DISTANCE_CATEGORIES,
    GRADE_MAPPING,
    TRACK_CONDITION_CODES,
)
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

# コード変換テーブル
DIRECTION_CODES = {"右": 0, "左": 1, "直線": 2}
SURFACE_CODES = {"芝": 0, "ダート": 1, "障害": 2}


class FastFeaturePipeline:
    """全データをメモリにロードして高速に特徴量を生成するパイプライン"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._races: Optional[pd.DataFrame] = None
        self._results: Optional[pd.DataFrame] = None
        self._base_times: Optional[Dict] = None

    def _load_all_data(self):
        """全データをメモリにロードする"""
        logger.info("Loading all data into memory...")
        conn = sqlite3.connect(self.db_path, timeout=30)

        self._races = pd.read_sql(
            "SELECT * FROM races ORDER BY race_date", conn
        )
        self._results = pd.read_sql(
            "SELECT * FROM race_results", conn
        )
        # horse_history もロード (あれば)
        try:
            self._history = pd.read_sql(
                "SELECT * FROM horse_history ORDER BY horse_id, race_date DESC", conn
            )
        except Exception:
            self._history = pd.DataFrame()

        conn.close()

        logger.info(
            "Loaded: %d races, %d results, %d history rows",
            len(self._races), len(self._results),
            len(self._history) if not self._history.empty else 0,
        )

        # インデックス構築
        self._build_indices()
        # 基準タイム事前計算
        self._precompute_base_times()

    def _build_indices(self):
        """高速検索用インデックスを構築"""
        # race_id → race dict
        self._race_dict = {}
        for _, row in self._races.iterrows():
            self._race_dict[row["race_id"]] = row.to_dict()

        # race_id → [result dicts]
        self._results_by_race = defaultdict(list)
        for _, row in self._results.iterrows():
            self._results_by_race[row["race_id"]].append(row.to_dict())

        # horse_id → [(race_date, result_dict with race info)]
        # race_results + races を結合して馬別に整理
        merged = self._results.merge(
            self._races[["race_id", "race_date", "venue_code", "venue_name",
                         "race_type", "distance", "track_condition", "horse_count",
                         "grade"]],
            on="race_id", how="left"
        )
        self._horse_history_dict = defaultdict(list)
        for _, row in merged.iterrows():
            hid = row["horse_id"]
            if pd.notna(hid):
                self._horse_history_dict[hid].append(row.to_dict())

        # 日付でソート (降順: 最新が先)
        for hid in self._horse_history_dict:
            self._horse_history_dict[hid].sort(
                key=lambda x: x.get("race_date", ""), reverse=True
            )

        # jockey_id → [(race_date, result_dict with race info)]
        self._jockey_history_dict = defaultdict(list)
        for _, row in merged.iterrows():
            jid = row.get("jockey_id")
            if pd.notna(jid) and jid:
                self._jockey_history_dict[jid].append(row.to_dict())

        for jid in self._jockey_history_dict:
            self._jockey_history_dict[jid].sort(
                key=lambda x: x.get("race_date", ""), reverse=True
            )

        logger.info(
            "Built indices: %d horses, %d jockeys",
            len(self._horse_history_dict), len(self._jockey_history_dict)
        )

    def _precompute_base_times(self):
        """基準タイムを事前計算: (venue_code, distance, race_type, track_condition) → median time"""
        self._base_times = {}

        merged = self._results.merge(
            self._races[["race_id", "race_date", "venue_code", "race_type",
                         "distance", "track_condition"]],
            on="race_id", how="left"
        )

        # 上位5着のみで基準タイム算出
        top5 = merged[
            (merged["finish_order"].notna()) &
            (merged["finish_order"] <= 5) &
            (merged["finish_time"].notna()) &
            (merged["finish_time"] > 0)
        ].copy()

        grouped = top5.groupby(["venue_code", "distance", "race_type", "track_condition"])
        for key, group in grouped:
            median_time = group["finish_time"].median()
            self._base_times[key] = median_time

        logger.info("Precomputed %d base times", len(self._base_times))

    def _get_base_time(self, venue_code, distance, race_type, track_condition) -> Optional[float]:
        """事前計算済み基準タイムを取得"""
        key = (venue_code, distance, race_type, track_condition)
        bt = self._base_times.get(key)
        if bt is not None:
            return bt
        # 馬場状態を無視してフォールバック
        for k, v in self._base_times.items():
            if k[0] == venue_code and k[1] == distance and k[2] == race_type:
                return v
        return None

    def _get_horse_past(self, horse_id: str, before_date: str) -> List[Dict]:
        """指定日以前の馬の出走履歴を取得"""
        history = self._horse_history_dict.get(horse_id, [])
        return [h for h in history if h.get("race_date", "9999") < before_date]

    def _get_jockey_past_1y(self, jockey_id: str, before_date: str) -> List[Dict]:
        """騎手の1年以内の成績を取得"""
        if not jockey_id:
            return []
        history = self._jockey_history_dict.get(jockey_id, [])
        try:
            dt = pd.Timestamp(before_date)
            start = (dt - pd.DateOffset(years=1)).strftime("%Y-%m-%d")
        except Exception:
            return []
        return [
            h for h in history
            if start <= h.get("race_date", "") < before_date
        ]

    # ===== Speed Index Features (3) =====
    def _compute_speed_features(self, horse_id: str, before_date: str) -> Dict:
        """スピード指数 (3特徴量)"""
        past = self._get_horse_past(horse_id, before_date)[:10]
        indices = []

        for h in past:
            ft = h.get("finish_time")
            if not ft or ft <= 0:
                continue
            vc = h.get("venue_code")
            dist = h.get("distance")
            rt = h.get("race_type")
            tc = h.get("track_condition")
            base = self._get_base_time(vc, dist, rt, tc)
            if base and base > 0:
                si = (base - ft) / base * 100 + 50
                indices.append(si)

        if not indices:
            return {"speed_index_last3": None, "speed_index_best3": None, "speed_index_std": None}

        last3 = indices[:3]
        best3 = sorted(indices, reverse=True)[:3]
        return {
            "speed_index_last3": np.mean(last3),
            "speed_index_best3": np.mean(best3),
            "speed_index_std": np.std(indices) if len(indices) >= 2 else 0.0,
        }

    # ===== Pace Index Features (2) =====
    def _compute_pace_features(self, horse_id: str, before_date: str) -> Dict:
        """ペース指数 (2特徴量)"""
        past = self._get_horse_past(horse_id, before_date)[:5]
        pace_indices = []
        styles = []

        for h in past:
            ft = h.get("finish_time")
            f3f = h.get("final_3f")
            corners = h.get("corner_positions", "")

            if ft and ft > 0 and f3f and f3f > 0:
                early_time = ft - f3f
                if early_time > 0:
                    pace = early_time / f3f
                    pace_indices.append(pace)

            # Running style from corner positions
            if corners and isinstance(corners, str):
                positions = []
                for p in corners.replace("-", ",").split(","):
                    p = p.strip()
                    if p.isdigit():
                        positions.append(int(p))
                if positions:
                    avg_pos = np.mean(positions[:2]) if len(positions) >= 2 else positions[0]
                    hc = h.get("horse_count", 18)
                    if hc and hc > 0:
                        ratio = avg_pos / hc
                        if ratio <= 0.2:
                            styles.append(0)  # 逃げ
                        elif ratio <= 0.4:
                            styles.append(1)  # 先行
                        elif ratio <= 0.7:
                            styles.append(2)  # 差し
                        else:
                            styles.append(3)  # 追込

        return {
            "pace_index_last3": np.mean(pace_indices[:3]) if pace_indices else None,
            "running_style": float(max(set(styles), key=styles.count)) if styles else 2.0,
        }

    # ===== Track Switch Features (5) =====
    def _compute_track_switch_features(
        self, horse_id: str, before_date: str,
        current_race: Dict, past: List[Dict]
    ) -> Dict:
        """トラック替わり特徴量 (5特徴量)

        - is_first_dirt: 初ダート出走フラグ
        - is_first_turf: 初芝出走フラグ
        - career_at_switch: トラック替わり時のキャリア数 (非替わり=0)
        - prev_surface_runs: 前の馬場での連続出走数
        - prev_weight_for_switch: 前走馬体重 (朝予想用。直前予想では当日馬体重を使用)
        """
        cur_surface = current_race.get("race_type")
        features = {
            "is_first_dirt": 0.0,
            "is_first_turf": 0.0,
            "career_at_switch": 0.0,
            "prev_surface_runs": 0.0,
            "prev_weight_for_switch": 0.0,
        }

        if not past or not cur_surface:
            return features

        # 過去走の馬場を取得（race_typeがあるもののみ）
        past_surfaces = [
            h["race_type"] for h in past
            if h.get("race_type") and h["race_type"] in ("芝", "ダート")
        ]

        if not past_surfaces:
            return features

        # 初ダート・初芝フラグ
        if cur_surface == "ダート" and "ダート" not in past_surfaces:
            features["is_first_dirt"] = 1.0
            features["career_at_switch"] = float(len(past_surfaces))
        elif cur_surface == "芝" and "芝" not in past_surfaces:
            features["is_first_turf"] = 1.0
            features["career_at_switch"] = float(len(past_surfaces))

        # 前の馬場での連続出走数（直前から数えて同じ馬場が何連続か）
        if past_surfaces:
            prev_surface = past_surfaces[0]
            streak = 0
            for s in past_surfaces:
                if s == prev_surface:
                    streak += 1
                else:
                    break
            features["prev_surface_runs"] = float(streak)

        # 前走の馬体重（朝予想用のベースライン）
        for h in past:
            hw = h.get("horse_weight")
            if hw and hw > 0:
                features["prev_weight_for_switch"] = float(hw)
                break

        return features

    # ===== Horse Features (25) =====
    def _compute_horse_features(
        self, horse_id: str, before_date: str,
        current_race: Dict, current_result: Dict
    ) -> Dict:
        """馬固有特徴量 (25特徴量)"""
        past = self._get_horse_past(horse_id, before_date)
        features: Dict = {}

        n = len(past)
        if n == 0:
            return self._default_horse_features(current_race, current_result)

        # 勝率・複勝率 (全体)
        wins = sum(1 for h in past if h.get("finish_order") == 1)
        top3 = sum(1 for h in past if h.get("finish_order") and h["finish_order"] <= 3)
        features["win_rate_all"] = wins / n
        features["top3_rate_all"] = top3 / n

        # 勝率・複勝率 (直近5走)
        recent5 = past[:5]
        n5 = len(recent5)
        wins5 = sum(1 for h in recent5 if h.get("finish_order") == 1)
        top3_5 = sum(1 for h in recent5 if h.get("finish_order") and h["finish_order"] <= 3)
        features["win_rate_recent5"] = wins5 / n5
        features["top3_rate_recent5"] = top3_5 / n5

        # 平均着順
        finish_orders = [h["finish_order"] for h in past if h.get("finish_order")]
        features["avg_finish_position"] = np.mean(finish_orders) if finish_orders else 9.0

        # 上がり3F
        f3fs = [h["final_3f"] for h in past if h.get("final_3f") and h["final_3f"] > 0]
        features["final_3f_avg"] = np.mean(f3fs) if f3fs else None
        features["final_3f_best"] = min(f3fs) if f3fs else None

        # 馬体重
        hw = current_result.get("horse_weight")
        features["horse_weight"] = float(hw) if hw else None
        wc = current_result.get("weight_change")
        features["weight_change"] = float(wc) if wc else 0.0

        # 休養日数
        if past and past[0].get("race_date"):
            try:
                last_date = pd.Timestamp(past[0]["race_date"])
                current_date = pd.Timestamp(before_date)
                features["days_since_last_race"] = (current_date - last_date).days
            except Exception:
                features["days_since_last_race"] = 180.0
        else:
            features["days_since_last_race"] = 180.0

        # 年齢・性別
        sex_age = current_result.get("sex_age", "")
        features["age"] = self._parse_age(sex_age)
        features["sex_code"] = self._parse_sex(sex_age)

        # キャリアレース数
        features["career_races"] = float(n)

        # 距離別勝率
        cur_dist = current_race.get("distance")
        dist_races = [h for h in past if h.get("distance") == cur_dist]
        features["distance_wins"] = (
            sum(1 for h in dist_races if h.get("finish_order") == 1) / len(dist_races)
            if dist_races else 0.0
        )

        # 馬場種別別勝率
        cur_surface = current_race.get("race_type")
        surf_races = [h for h in past if h.get("race_type") == cur_surface]
        features["surface_wins"] = (
            sum(1 for h in surf_races if h.get("finish_order") == 1) / len(surf_races)
            if surf_races else 0.0
        )

        # 競馬場別勝率
        cur_venue = current_race.get("venue_code")
        venue_races = [h for h in past if h.get("venue_code") == cur_venue]
        features["venue_wins"] = (
            sum(1 for h in venue_races if h.get("finish_order") == 1) / len(venue_races)
            if venue_races else 0.0
        )

        # 馬場状態別成績
        cur_cond = current_race.get("track_condition")
        cond_races = [h for h in past if h.get("track_condition") == cur_cond]
        if cond_races:
            cond_finishes = [h["finish_order"] for h in cond_races if h.get("finish_order")]
            features["condition_perf"] = np.mean(cond_finishes) if cond_finishes else 9.0
        else:
            features["condition_perf"] = 9.0

        # クラスレベル
        features["class_level"] = self._get_class_level(current_race)

        # コーナー通過順位平均
        corner_avgs = []
        for h in recent5:
            cp = h.get("corner_positions", "")
            if cp and isinstance(cp, str):
                positions = []
                for p in cp.replace("-", ",").split(","):
                    p = p.strip()
                    if p.isdigit():
                        positions.append(int(p))
                if positions:
                    corner_avgs.append(np.mean(positions))
        features["corner_position_avg"] = np.mean(corner_avgs) if corner_avgs else 9.0

        # 斤量差
        wc_val = current_result.get("weight_carry")
        if wc_val:
            past_carries = [h.get("weight_carry") for h in past if h.get("weight_carry")]
            if past_carries:
                features["weight_carry_diff"] = float(wc_val) - np.mean(past_carries)
            else:
                features["weight_carry_diff"] = 0.0
        else:
            features["weight_carry_diff"] = 0.0

        return features

    def _default_horse_features(self, race: Dict, result: Dict) -> Dict:
        """出走履歴がない馬のデフォルト特徴量"""
        sex_age = result.get("sex_age", "")
        return {
            "win_rate_all": 0.0, "top3_rate_all": 0.0,
            "win_rate_recent5": 0.0, "top3_rate_recent5": 0.0,
            "avg_finish_position": 9.0,
            "final_3f_avg": None, "final_3f_best": None,
            "horse_weight": float(result.get("horse_weight") or 0) if result.get("horse_weight") else None,
            "weight_change": float(result.get("weight_change") or 0),
            "days_since_last_race": 365.0,
            "age": self._parse_age(sex_age),
            "sex_code": self._parse_sex(sex_age),
            "career_races": 0.0,
            "distance_wins": 0.0, "surface_wins": 0.0,
            "venue_wins": 0.0, "condition_perf": 9.0,
            "class_level": self._get_class_level(race),
            "corner_position_avg": 9.0, "weight_carry_diff": 0.0,
        }

    # ===== Jockey Features (10) =====
    def _compute_jockey_features(
        self, jockey_id: str, horse_id: str, trainer_id: str,
        before_date: str, venue_code: str, surface_type: str,
        distance: int, weight_carry: float
    ) -> Dict:
        """騎手特徴量 (10特徴量)"""
        past = self._get_jockey_past_1y(jockey_id, before_date)
        features: Dict = {}

        n = len(past)
        if n == 0:
            return {
                "jockey_win_rate_1y": 0.0, "jockey_top3_rate_1y": 0.0,
                "jockey_venue_rate": 0.0, "jockey_surface_rate": 0.0,
                "jockey_distance_rate": 0.0, "jockey_trainer_combo": 0.0,
                "jockey_horse_combo": 0.0, "jockey_avg_odds_win": 0.0,
                "jockey_change_flag": 0.0, "jockey_weight_range": 0.0,
            }

        wins = sum(1 for h in past if h.get("finish_order") == 1)
        top3 = sum(1 for h in past if h.get("finish_order") and h["finish_order"] <= 3)
        features["jockey_win_rate_1y"] = wins / n
        features["jockey_top3_rate_1y"] = top3 / n

        # Venue rate
        venue_races = [h for h in past if h.get("venue_code") == venue_code]
        if venue_races:
            features["jockey_venue_rate"] = (
                sum(1 for h in venue_races if h.get("finish_order") == 1) / len(venue_races)
            )
        else:
            features["jockey_venue_rate"] = features["jockey_win_rate_1y"]

        # Surface rate
        surf_races = [h for h in past if h.get("race_type") == surface_type]
        if surf_races:
            features["jockey_surface_rate"] = (
                sum(1 for h in surf_races if h.get("finish_order") == 1) / len(surf_races)
            )
        else:
            features["jockey_surface_rate"] = features["jockey_win_rate_1y"]

        # Distance rate
        dist_races = [h for h in past if h.get("distance") == distance]
        if dist_races:
            features["jockey_distance_rate"] = (
                sum(1 for h in dist_races if h.get("finish_order") == 1) / len(dist_races)
            )
        else:
            features["jockey_distance_rate"] = features["jockey_win_rate_1y"]

        # Trainer combo
        trainer_races = [h for h in past if h.get("trainer_id") == trainer_id]
        if trainer_races:
            features["jockey_trainer_combo"] = (
                sum(1 for h in trainer_races if h.get("finish_order") == 1) / len(trainer_races)
            )
        else:
            features["jockey_trainer_combo"] = 0.0

        # Horse combo
        horse_races = [h for h in past if h.get("horse_id") == horse_id]
        if horse_races:
            features["jockey_horse_combo"] = (
                sum(1 for h in horse_races if h.get("finish_order") == 1) / len(horse_races)
            )
        else:
            features["jockey_horse_combo"] = 0.0

        # Avg odds on wins
        win_odds = [h.get("odds") for h in past if h.get("finish_order") == 1 and h.get("odds")]
        features["jockey_avg_odds_win"] = np.mean(win_odds) if win_odds else 0.0

        # Jockey change flag
        horse_past = self._get_horse_past(horse_id, before_date)
        if horse_past and horse_past[0].get("jockey_id"):
            features["jockey_change_flag"] = 1.0 if horse_past[0]["jockey_id"] != jockey_id else 0.0
        else:
            features["jockey_change_flag"] = 0.0

        # Weight range
        carries = [h.get("weight_carry") for h in past if h.get("weight_carry")]
        if carries:
            features["jockey_weight_range"] = max(carries) - min(carries)
        else:
            features["jockey_weight_range"] = 0.0

        return features

    # ===== Race Features (15) =====
    def _compute_race_features(self, race: Dict, result_row: Dict) -> Dict:
        """レース・コース特徴量 (15特徴量)"""
        features: Dict = {}

        features["horse_count"] = float(race.get("horse_count") or 0)
        features["distance"] = float(race.get("distance") or 0)
        features["distance_category"] = float(self._distance_category(race.get("distance")))

        race_type = race.get("race_type") or ""
        features["surface_type"] = float(SURFACE_CODES.get(race_type, 0))

        track_cond = race.get("track_condition") or ""
        features["track_condition_code"] = float(TRACK_CONDITION_CODES.get(track_cond, 0))

        venue_code = race.get("venue_code") or "00"
        try:
            features["venue_code"] = float(int(venue_code))
        except (ValueError, TypeError):
            features["venue_code"] = 0.0

        direction = race.get("direction") or ""
        features["direction_code"] = float(DIRECTION_CODES.get(direction, 0))

        grade = race.get("grade") or ""
        features["grade_code"] = float(GRADE_MAPPING.get(grade, 0))

        race_date = race.get("race_date") or ""
        try:
            features["month"] = float(int(race_date.split("-")[1]))
        except (IndexError, ValueError, TypeError):
            features["month"] = 0.0

        features["is_special_race"] = 1.0 if grade in ("G1", "G2", "G3") else 0.0
        features["frame_number"] = float(result_row.get("frame_number") or 0)
        features["horse_number"] = float(result_row.get("horse_number") or 0)

        # post_position_bias はレース全体で計算するため後で設定
        features["post_position_bias"] = 0.0
        # field_quality はレース全体で計算するため後で設定
        features["field_quality"] = None

        return features

    # ===== Market Features (10) =====
    def _compute_market_features(self, result_row: Dict, all_results: List[Dict]) -> Dict:
        """市場特徴量 (10特徴量)"""
        features: Dict = {}

        odds = result_row.get("odds")
        pop = result_row.get("popularity")

        features["odds"] = float(odds) if odds else 0.0
        features["log_odds"] = math.log(float(odds)) if odds and float(odds) > 0 else 0.0
        features["popularity"] = float(pop) if pop else 0.0
        features["implied_probability"] = 1.0 / float(odds) if odds and float(odds) > 0 else 0.0

        # All odds
        all_odds = sorted(
            [float(r.get("odds", 0)) for r in all_results if r.get("odds") and float(r.get("odds", 0)) > 0]
        )

        if len(all_odds) >= 2:
            features["odds_gap_1st_2nd"] = all_odds[1] / all_odds[0] if all_odds[0] > 0 else 0.0
            features["favorite_strength"] = 1.0 / all_odds[0] if all_odds[0] > 0 else 0.0
        else:
            features["odds_gap_1st_2nd"] = 0.0
            features["favorite_strength"] = 0.0

        # Concentration
        if all_odds:
            total_inv = sum(1.0 / o for o in all_odds if o > 0)
            if total_inv > 0:
                probs = [(1.0 / o) / total_inv for o in all_odds if o > 0]
                features["odds_concentration"] = -sum(p * math.log(p + 1e-10) for p in probs)
            else:
                features["odds_concentration"] = 0.0
        else:
            features["odds_concentration"] = 0.0

        features["model_vs_market"] = 0.0  # populated after model prediction
        features["expected_value"] = 0.0   # populated after model prediction

        return features

    # ===== Build =====
    def build_features(self, start_date: str, end_date: str) -> pd.DataFrame:
        """全レースの特徴量行列を構築する"""
        if self._races is None:
            self._load_all_data()

        # 対象レース取得
        mask = (self._races["race_date"] >= start_date) & (self._races["race_date"] <= end_date)
        target_races = self._races[mask]
        logger.info("Building features for %d races (%s to %s)", len(target_races), start_date, end_date)

        all_rows = []
        for i, (_, race_row) in enumerate(target_races.iterrows()):
            race_id = race_row["race_id"]
            race_date = race_row["race_date"]
            race = race_row.to_dict()
            results = self._results_by_race.get(race_id, [])

            if not results:
                continue

            speed_indices_for_field = []

            for result_row in results:
                horse_id = result_row.get("horse_id")
                if not horse_id:
                    continue

                row = {
                    "race_id": race_id,
                    "race_date": race_date,
                    "horse_id": horse_id,
                    "horse_name": result_row.get("horse_name", ""),
                    "horse_number": result_row.get("horse_number"),
                    "finish_order": result_row.get("finish_order"),
                }

                # Speed index features (3)
                speed = self._compute_speed_features(horse_id, race_date)
                row.update(speed)
                if speed.get("speed_index_last3") is not None:
                    speed_indices_for_field.append(speed["speed_index_last3"])

                # Pace index features (2)
                pace = self._compute_pace_features(horse_id, race_date)
                row.update(pace)

                # Horse features (25)
                horse = self._compute_horse_features(horse_id, race_date, race, result_row)
                row.update(horse)

                # Track switch features (5)
                horse_past = self._get_horse_past(horse_id, race_date)
                track_switch = self._compute_track_switch_features(
                    horse_id, race_date, race, horse_past
                )
                row.update(track_switch)

                # Jockey features (10)
                jockey = self._compute_jockey_features(
                    jockey_id=result_row.get("jockey_id", ""),
                    horse_id=horse_id,
                    trainer_id=result_row.get("trainer_id", ""),
                    before_date=race_date,
                    venue_code=race.get("venue_code"),
                    surface_type=race.get("race_type"),
                    distance=race.get("distance"),
                    weight_carry=result_row.get("weight_carry"),
                )
                row.update(jockey)

                # Race features (15)
                race_feats = self._compute_race_features(race, result_row)
                row.update(race_feats)

                # Market features (10)
                market = self._compute_market_features(result_row, results)
                row.update(market)

                all_rows.append(row)

            # field_quality
            if speed_indices_for_field:
                fq = np.mean(speed_indices_for_field)
                for row in all_rows[-len(results):]:
                    if row.get("race_id") == race_id:
                        row["field_quality"] = fq

            if (i + 1) % 500 == 0:
                logger.info("Processed %d / %d races", i + 1, len(target_races))

        if not all_rows:
            return pd.DataFrame()

        df = pd.DataFrame(all_rows)

        # 欠損値処理
        meta_cols = {"race_id", "race_date", "horse_id", "horse_name", "finish_order", "horse_number"}
        numeric_cols = [
            c for c in df.columns
            if c not in meta_cols and df[c].dtype in ("float64", "int64", "float32", "int32")
        ]
        for col in numeric_cols:
            if df[col].isna().any():
                median_val = df[col].median()
                if pd.isna(median_val):
                    median_val = 0.0
                df[col] = df[col].fillna(median_val)
        for col in df.columns:
            if col not in meta_cols and df[col].isna().any():
                df[col] = df[col].fillna(0.0)

        logger.info("Built feature matrix: %d rows x %d cols", len(df), len(df.columns))
        return df

    # ===== Utility =====
    @staticmethod
    def _parse_age(sex_age: str) -> float:
        if not sex_age or len(sex_age) < 2:
            return 3.0
        try:
            return float(sex_age[1:])
        except ValueError:
            return 3.0

    @staticmethod
    def _parse_sex(sex_age: str) -> float:
        if not sex_age:
            return 0.0
        s = sex_age[0]
        return {"牡": 0.0, "牝": 1.0, "セ": 2.0}.get(s, 0.0)

    @staticmethod
    def _distance_category(distance) -> int:
        if distance is None:
            return 2
        for i, (cat, (low, high)) in enumerate(DISTANCE_CATEGORIES.items()):
            if low <= distance <= high:
                return i
        return 2

    @staticmethod
    def _get_class_level(race: Dict) -> float:
        grade = race.get("grade") or ""
        mapping = {"G1": 6, "G2": 5, "G3": 4, "OP": 3, "L": 3}
        return float(mapping.get(grade, 1))
