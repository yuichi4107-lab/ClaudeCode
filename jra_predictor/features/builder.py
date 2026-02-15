import logging
from datetime import datetime

import numpy as np
import pandas as pd

from jra_predictor.storage.repository import Repository
from jra_predictor.config.settings import (
    VENUE_CODES,
    TRACK_CONDITION_ENC,
    TRACK_TYPE_ENC,
    COURSE_DIRECTION_ENC,
)

logger = logging.getLogger(__name__)

NUMERIC_FEATURES = [
    # 馬の過去成績 (13)
    "horse_last1_finish",
    "horse_last3_avg_finish",
    "horse_last5_win_rate",
    "horse_last5_top3_rate",
    "horse_career_win_rate",
    "horse_days_since_last",
    "horse_same_venue_win_rate",
    "horse_same_dist_win_rate",
    "horse_same_track_type_win_rate",
    "horse_speed_index_last1",
    "horse_speed_index_last3",
    "horse_weight_change",
    "horse_avg_last3f",
    # 騎手 (3)
    "jockey_win_rate_overall",
    "jockey_win_rate_venue",
    "jockey_horse_pair_wins",
    # レース情報 (7)
    "field_size",
    "distance",
    "venue_enc",
    "track_type_enc",
    "track_cond_enc",
    "course_direction_enc",
    "race_number",
    # 出走馬情報 (5)
    "gate_number",
    "horse_number",
    "weight_carried",
    "horse_weight",
    "popularity_rank",
]


def _speed_index(row: pd.Series) -> float:
    """スピード指数 = 距離(m) / タイム(秒)。高いほど速い。"""
    dist = row.get("distance")
    t = row.get("finish_time")
    if dist and t and t > 0:
        return dist / t
    return np.nan


def _days_between(date_a: str, date_b: str) -> float:
    """date_a - date_b の日数差（正の値）。"""
    try:
        da = datetime.strptime(date_a[:10], "%Y-%m-%d")
        db = datetime.strptime(date_b[:10], "%Y-%m-%d")
        return (da - db).days
    except Exception:
        return np.nan


class FeatureBuilder:
    """
    race_entries + horse_history_cache + jockeys を結合して
    scikit-learn 用の特徴量 DataFrame を生成する。

    重要: 特徴量生成時は必ず対象レース日付より前のデータのみ使用する
    （未来情報の混入防止）。
    """

    def __init__(self, repo: Repository):
        self.repo = repo

    # ------------------------------------------------------------------ public

    def build_training_set(
        self, from_date: str, to_date: str, target: str = "win"
    ) -> tuple[pd.DataFrame, pd.Series]:
        """
        Returns (X, y):
          X: 特徴量行列（1行=1出走）
          y: ラベル。target="win" -> 1着, target="place" -> 2着
        """
        entries_df = self.repo.get_entries_in_range(from_date, to_date)
        logger.info(
            "Building features for %d entries (%s ~ %s) target=%s",
            len(entries_df),
            from_date,
            to_date,
            target,
        )

        feature_rows = []
        for _, entry in entries_df.iterrows():
            row = self._build_row(entry)
            feature_rows.append(row)

        df = pd.DataFrame(feature_rows)
        if target == "place":
            y = df.pop("is_second").astype(int)
            if "is_winner" in df.columns:
                df.pop("is_winner")
        else:
            y = df.pop("is_winner").astype(int)
            if "is_second" in df.columns:
                df.pop("is_second")
        X = df[NUMERIC_FEATURES]

        # 欠損率が極端に高い特徴量を除外
        missing_rate = X.isna().mean()
        threshold = 0.8
        drop_cols = missing_rate[missing_rate > threshold].index.tolist()
        if drop_cols:
            logger.info("Dropping features with missing rate > %.2f: %s", threshold, drop_cols)
            X = X.drop(columns=drop_cols)

        return X, y

    def build_prediction_rows(
        self, race_id: str, entries: list[dict], race_info: dict
    ) -> pd.DataFrame:
        """
        出馬表エントリーから予測用特徴量を生成する。
        """
        rows = []
        for entry in entries:
            entry_series = pd.Series({**entry, **race_info})
            row = self._build_row(entry_series)
            row["horse_number"] = entry.get("horse_number")
            row["horse_name"] = entry.get("horse_name")
            rows.append(row)

        df = pd.DataFrame(rows)
        for col in NUMERIC_FEATURES:
            if col not in df.columns:
                df[col] = np.nan

        return df

    # --------------------------------------------------------------- private

    def _build_row(self, entry: pd.Series) -> dict:
        row = {}
        row.update(self._horse_features(entry))
        row.update(self._jockey_features(entry))
        row.update(self._race_features(entry))
        row.update(self._entry_features(entry))
        row["is_winner"] = entry.get("is_winner")
        pos = entry.get("finish_position")
        row["is_second"] = 1 if pos == 2 else (0 if pos is not None else None)
        return row

    def _horse_features(self, entry: pd.Series) -> dict:
        horse_id = entry.get("horse_id")
        race_date = str(entry.get("race_date", ""))
        venue_name = entry.get("venue_name", "")
        distance = entry.get("distance")
        track_type = entry.get("track_type", "")

        null_feats = {
            "horse_last1_finish": np.nan,
            "horse_last3_avg_finish": np.nan,
            "horse_last5_win_rate": np.nan,
            "horse_last5_top3_rate": np.nan,
            "horse_career_win_rate": np.nan,
            "horse_days_since_last": np.nan,
            "horse_same_venue_win_rate": np.nan,
            "horse_same_dist_win_rate": np.nan,
            "horse_same_track_type_win_rate": np.nan,
            "horse_speed_index_last1": np.nan,
            "horse_speed_index_last3": np.nan,
            "horse_weight_change": entry.get("weight_change", np.nan),
            "horse_avg_last3f": np.nan,
        }

        if not horse_id or not race_date:
            return null_feats

        history = self.repo.get_horse_history(horse_id, before_date=race_date, limit=20)
        if history.empty:
            return null_feats

        last1 = history.iloc[0]
        last3 = history.head(3)
        last5 = history.head(5)

        same_venue = history[history["venue_name"] == venue_name]
        if distance:
            same_dist = history[
                history["distance"].apply(
                    lambda d: abs(d - distance) <= 100 if pd.notna(d) else False
                )
            ]
        else:
            same_dist = pd.DataFrame()

        # 同じコース種別（芝/ダート）での成績
        if track_type:
            same_track = history[history["track_type"] == track_type]
        else:
            same_track = pd.DataFrame()

        return {
            "horse_last1_finish": last1["finish_position"],
            "horse_last3_avg_finish": last3["finish_position"].mean(),
            "horse_last5_win_rate": (last5["finish_position"] == 1).mean(),
            "horse_last5_top3_rate": (last5["finish_position"] <= 3).mean(),
            "horse_career_win_rate": (history["finish_position"] == 1).mean(),
            "horse_days_since_last": _days_between(race_date, str(last1["race_date"])),
            "horse_same_venue_win_rate": (
                (same_venue["finish_position"] == 1).mean()
                if len(same_venue) > 0
                else np.nan
            ),
            "horse_same_dist_win_rate": (
                (same_dist["finish_position"] == 1).mean()
                if len(same_dist) > 0
                else np.nan
            ),
            "horse_same_track_type_win_rate": (
                (same_track["finish_position"] == 1).mean()
                if len(same_track) > 0
                else np.nan
            ),
            "horse_speed_index_last1": _speed_index(last1),
            "horse_speed_index_last3": last3.apply(_speed_index, axis=1).mean(),
            "horse_weight_change": entry.get("weight_change", np.nan),
            "horse_avg_last3f": np.nan,  # 上がり3Fは horse_history_cache に未保存のため近似
        }

    def _jockey_features(self, entry: pd.Series) -> dict:
        jockey_id = entry.get("jockey_id")
        race_date = str(entry.get("race_date", ""))
        venue_code = entry.get("venue_code")

        null_feats = {
            "jockey_win_rate_overall": np.nan,
            "jockey_win_rate_venue": np.nan,
            "jockey_horse_pair_wins": np.nan,
        }

        if not jockey_id or not race_date:
            return null_feats

        overall = self.repo.get_jockey_stats(jockey_id, before_date=race_date)
        venue_stats = self.repo.get_jockey_stats(
            jockey_id, before_date=race_date, venue_code=venue_code
        )

        overall_win_rate = (
            (overall["finish_position"] == 1).mean() if len(overall) > 0 else np.nan
        )
        venue_win_rate = (
            (venue_stats["finish_position"] == 1).mean()
            if len(venue_stats) > 0
            else np.nan
        )

        pair_wins = np.nan

        return {
            "jockey_win_rate_overall": overall_win_rate,
            "jockey_win_rate_venue": venue_win_rate,
            "jockey_horse_pair_wins": pair_wins,
        }

    def _race_features(self, entry: pd.Series) -> dict:
        venue_code = entry.get("venue_code", "")
        venue_values = list(VENUE_CODES.values())
        venue_enc = venue_values.index(venue_code) if venue_code in venue_values else np.nan
        track_type = entry.get("track_type", "")
        track_cond = entry.get("track_condition", "")
        course_dir = entry.get("course_direction", "")

        return {
            "field_size": entry.get("field_size", np.nan),
            "distance": entry.get("distance", np.nan),
            "venue_enc": venue_enc,
            "track_type_enc": TRACK_TYPE_ENC.get(track_type, np.nan),
            "track_cond_enc": TRACK_CONDITION_ENC.get(track_cond, np.nan),
            "course_direction_enc": COURSE_DIRECTION_ENC.get(course_dir, np.nan),
            "race_number": entry.get("race_number", np.nan),
        }

    def _entry_features(self, entry: pd.Series) -> dict:
        return {
            "gate_number": entry.get("gate_number", np.nan),
            "horse_number": entry.get("horse_number", np.nan),
            "weight_carried": entry.get("weight_carried", np.nan),
            "horse_weight": entry.get("horse_weight", np.nan),
            "popularity_rank": entry.get("popularity_rank", np.nan),
        }
