"""ばんえい競馬用特徴量エンジニアリング

ばんえい競馬特有の特徴量を生成する。
- 馬体重（重量級の馬が有利になる場合がある）
- 負担重量（ソリの重さ）
- 騎手・調教師の成績
- 過去走の着順・タイム
- 距離適性
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from config.settings import PAST_RACE_COUNT, PROCESSED_DATA_DIR

logger = logging.getLogger(__name__)


class FeatureEngineer:
    """特徴量生成クラス"""

    def __init__(self, df: pd.DataFrame):
        self.df = df.copy()
        self._preprocess()

    def _preprocess(self):
        """基本的な前処理"""
        if "race_date" in self.df.columns:
            self.df["race_date"] = pd.to_datetime(self.df["race_date"])
        self.df = self.df.sort_values(
            ["race_date", "race_no", "horse_number"]
        ).reset_index(drop=True)

        # 1着かどうかのターゲット変数
        self.df["is_win"] = (self.df["finish_order"] == 1).astype(int)

        # タイムを秒に変換
        if "time" in self.df.columns:
            self.df["time_seconds"] = self.df["time"].apply(self._time_to_seconds)

        # 性別と年齢を分離（まだ無い場合）
        if "sex_age" in self.df.columns and "sex" not in self.df.columns:
            self.df["sex"] = self.df["sex_age"].str[0]
            self.df["age"] = pd.to_numeric(
                self.df["sex_age"].str[1:], errors="coerce"
            )

    @staticmethod
    def _time_to_seconds(time_str: str) -> float | None:
        """タイム文字列を秒に変換 (例: '1:23.4' -> 83.4)"""
        if not time_str or not isinstance(time_str, str):
            return None
        try:
            time_str = time_str.strip()
            if ":" in time_str:
                parts = time_str.split(":")
                minutes = int(parts[0])
                seconds = float(parts[1])
                return minutes * 60 + seconds
            return float(time_str)
        except (ValueError, IndexError):
            return None

    def build_features(self) -> pd.DataFrame:
        """全特徴量を生成して返す"""
        df = self.df.copy()

        df = self._add_horse_past_features(df)
        df = self._add_person_expanding_stats(df, "jockey", "jockey")
        df = self._add_person_expanding_stats(df, "trainer", "trainer")
        df = self._add_weight_features(df)
        df = self._add_race_features(df)

        return df

    def _add_horse_past_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """馬の過去成績に基づく特徴量（ベクトル化版）"""
        df = df.copy()
        df["_is_top3"] = (df["finish_order"] <= 3).astype(float)

        init_cols = {
            "past_runs": 0,
            "past_win_rate": np.nan,
            "past_top3_rate": np.nan,
            "past_avg_finish": np.nan,
            "past_best_finish": np.nan,
            "past_avg_time": np.nan,
            "past_best_time": np.nan,
            "days_since_last_race": np.nan,
        }
        for col, val in init_cols.items():
            df[col] = val

        has_time = "time_seconds" in df.columns

        for horse_name, group in df.groupby("horse_name"):
            idxs = group.index.tolist()
            finish_orders = pd.to_numeric(group["finish_order"], errors="coerce").values
            dates = group["race_date"].values
            is_win = np.where(np.isnan(finish_orders), 0, (finish_orders == 1)).astype(float)
            is_top3 = np.where(np.isnan(finish_orders), 0, (finish_orders <= 3)).astype(float)
            times = group["time_seconds"].values if has_time else None

            for i in range(len(idxs)):
                start = max(0, i - PAST_RACE_COUNT)
                if start == i:
                    continue  # 過去データなし

                past_finish = finish_orders[start:i]
                past_wins = is_win[start:i]
                past_top3 = is_top3[start:i]
                past_dates = dates[start:i]

                idx = idxs[i]
                n = len(past_finish)
                df.at[idx, "past_runs"] = n
                df.at[idx, "past_win_rate"] = past_wins.mean()
                df.at[idx, "past_top3_rate"] = past_top3.mean()
                df.at[idx, "past_avg_finish"] = past_finish.mean()
                df.at[idx, "past_best_finish"] = past_finish.min()

                if has_time and times is not None:
                    past_times = times[start:i]
                    valid = past_times[~np.isnan(past_times)]
                    if len(valid) > 0:
                        df.at[idx, "past_avg_time"] = valid.mean()
                        df.at[idx, "past_best_time"] = valid.min()

                days = (dates[i] - past_dates[-1]) / np.timedelta64(1, "D")
                df.at[idx, "days_since_last_race"] = days

        df.drop(columns=["_is_top3"], inplace=True)
        return df

    def _add_person_expanding_stats(
        self, df: pd.DataFrame, column: str, prefix: str
    ) -> pd.DataFrame:
        """騎手/調教師の累積成績を expanding window で計算"""
        df = df.copy()
        win_col = f"{prefix}_win_rate"
        top3_col = f"{prefix}_top3_rate"
        df[win_col] = np.nan
        df[top3_col] = np.nan

        if column not in df.columns:
            return df

        df["_is_win_float"] = df["is_win"].astype(float)
        df["_is_top3_float"] = (df["finish_order"] <= 3).astype(float)

        for name, group in df.groupby(column):
            idxs = group.index.tolist()
            wins = group["_is_win_float"].values
            top3s = group["_is_top3_float"].values

            cum_wins = np.cumsum(wins)
            cum_top3 = np.cumsum(top3s)
            counts = np.arange(1, len(idxs) + 1, dtype=float)

            # shift by 1 to use only past data
            for i in range(1, len(idxs)):
                df.at[idxs[i], win_col] = cum_wins[i - 1] / counts[i - 1]
                df.at[idxs[i], top3_col] = cum_top3[i - 1] / counts[i - 1]

        df.drop(columns=["_is_win_float", "_is_top3_float"], inplace=True)
        return df

    def _add_weight_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """重量関連の特徴量"""
        df = df.copy()

        if "horse_weight" in df.columns:
            df["weight_rank_in_race"] = df.groupby(
                ["race_date", "race_no"]
            )["horse_weight"].rank(ascending=False)

            race_mean = df.groupby(["race_date", "race_no"])[
                "horse_weight"
            ].transform("mean")
            df["weight_diff_from_mean"] = df["horse_weight"] - race_mean

        if "weight_carry" in df.columns:
            df["carry_rank_in_race"] = df.groupby(
                ["race_date", "race_no"]
            )["weight_carry"].rank(ascending=False)

            if "horse_weight" in df.columns:
                df["carry_to_weight_ratio"] = df["weight_carry"] / df[
                    "horse_weight"
                ].replace(0, np.nan)

        return df

    def _add_race_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """レース条件の特徴量"""
        df = df.copy()

        df["num_runners"] = df.groupby(["race_date", "race_no"])[
            "horse_number"
        ].transform("count")

        df["post_position_norm"] = df["post_position"] / df["num_runners"]

        if "race_date" in df.columns:
            df["month"] = df["race_date"].dt.month

        if "age" in df.columns:
            df["age"] = pd.to_numeric(df["age"], errors="coerce")

        if "sex" in df.columns:
            sex_map = {"牡": 0, "牝": 1, "セ": 2}
            df["sex_code"] = df["sex"].map(sex_map)

        return df

    def save(self, df: pd.DataFrame, filename: str = "features.csv"):
        """特徴量データを保存"""
        PROCESSED_DATA_DIR.mkdir(parents=True, exist_ok=True)
        filepath = PROCESSED_DATA_DIR / filename
        df.to_csv(filepath, index=False, encoding="utf-8-sig")
        logger.info("特徴量保存完了: %s (%d 件)", filepath, len(df))
        return filepath
