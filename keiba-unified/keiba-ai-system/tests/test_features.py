"""特徴量エンジニアリングのテスト"""

import numpy as np
import pandas as pd
import pytest

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.features.feature_engineering import FeatureEngineer


def _make_sample_df(n_dates=5, horses_per_race=6):
    """テスト用サンプルデータを生成"""
    import random

    random.seed(0)
    records = []
    horses = ["ウマA", "ウマB", "ウマC", "ウマD", "ウマE", "ウマF", "ウマG", "ウマH"]

    for d in range(n_dates):
        date_str = f"2025-01-{(d * 3 + 1):02d}"
        for race_no in range(1, 3):
            selected = random.sample(horses, horses_per_race)
            for i, h in enumerate(selected, 1):
                records.append(
                    {
                        "race_date": date_str,
                        "race_no": str(race_no),
                        "race_name": f"R{race_no}",
                        "distance": 200,
                        "finish_order": i,
                        "post_position": i,
                        "horse_number": i,
                        "horse_name": h,
                        "sex_age": random.choice(["牡4", "牝5", "セ6"]),
                        "horse_weight": random.randint(900, 1100),
                        "jockey": random.choice(["騎手A", "騎手B", "騎手C"]),
                        "time": f"2:{random.uniform(0, 30):04.1f}",
                        "weight_carry": random.choice([600, 620, 640, 660]),
                        "trainer": random.choice(["調教A", "調教B"]),
                        "odds": round(random.uniform(1.5, 20.0), 1),
                        "popularity": i,
                    }
                )
    return pd.DataFrame(records)


class TestFeatureEngineer:
    def test_build_features_returns_dataframe(self):
        df = _make_sample_df()
        fe = FeatureEngineer(df)
        result = fe.build_features()
        assert isinstance(result, pd.DataFrame)
        assert len(result) == len(df)

    def test_target_column_created(self):
        df = _make_sample_df()
        fe = FeatureEngineer(df)
        result = fe.build_features()
        assert "is_win" in result.columns
        assert result["is_win"].sum() > 0

    def test_past_features_exist(self):
        df = _make_sample_df()
        fe = FeatureEngineer(df)
        result = fe.build_features()
        expected_cols = [
            "past_runs",
            "past_win_rate",
            "past_top3_rate",
            "past_avg_finish",
            "past_best_finish",
            "past_avg_time",
            "past_best_time",
            "days_since_last_race",
        ]
        for col in expected_cols:
            assert col in result.columns, f"{col} が結果に含まれていません"

    def test_jockey_trainer_features(self):
        df = _make_sample_df()
        fe = FeatureEngineer(df)
        result = fe.build_features()
        for col in ["jockey_win_rate", "jockey_top3_rate", "trainer_win_rate", "trainer_top3_rate"]:
            assert col in result.columns

    def test_weight_features(self):
        df = _make_sample_df()
        fe = FeatureEngineer(df)
        result = fe.build_features()
        for col in ["weight_diff_from_mean", "carry_to_weight_ratio", "num_runners"]:
            assert col in result.columns

    def test_no_future_data_leakage(self):
        """過去データのみ使用し、未来のデータが漏れていないことを確認"""
        df = _make_sample_df(n_dates=10)
        fe = FeatureEngineer(df)
        result = fe.build_features()

        # 各馬の最初の出走レコードではpast_runsが0であるべき
        for horse, group in result.groupby("horse_name"):
            first_idx = group.index[0]
            assert group.loc[first_idx, "past_runs"] == 0, (
                f"{horse}の初出走でpast_runs != 0"
            )

    def test_time_to_seconds(self):
        assert FeatureEngineer._time_to_seconds("1:23.4") == 83.4
        assert FeatureEngineer._time_to_seconds("2:00.0") == 120.0
        assert FeatureEngineer._time_to_seconds("45.5") == 45.5
        assert FeatureEngineer._time_to_seconds("") is None
        assert FeatureEngineer._time_to_seconds(None) is None

    def test_sex_age_split(self):
        """sex_ageカラムからsexとageが正しく分離されること"""
        df = _make_sample_df()
        fe = FeatureEngineer(df)
        result = fe.build_features()
        assert "sex" in result.columns
        assert "age" in result.columns
        assert set(result["sex"].dropna().unique()).issubset({"牡", "牝", "セ"})
