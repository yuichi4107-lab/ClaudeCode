"""予測モデルのテスト"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.features.feature_engineering import FeatureEngineer
from src.model.predictor import BaneiPredictor


def _make_features_df():
    """特徴量付きのテスト用DataFrameを生成"""
    import random

    random.seed(42)
    records = []
    horses = ["ウマA", "ウマB", "ウマC", "ウマD", "ウマE", "ウマF"]

    for d in range(20):
        date_str = f"2025-{(d // 28 + 1):02d}-{(d % 28 + 1):02d}"
        for race_no in range(1, 3):
            selected = random.sample(horses, min(len(horses), 6))
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
                        "jockey": random.choice(["騎手A", "騎手B"]),
                        "time": f"2:{random.uniform(0, 30):04.1f}",
                        "weight_carry": random.choice([600, 620, 640]),
                        "trainer": random.choice(["調教A", "調教B"]),
                        "odds": round(random.uniform(1.5, 20.0), 1),
                        "popularity": i,
                    }
                )
    df = pd.DataFrame(records)
    fe = FeatureEngineer(df)
    return fe.build_features()


class TestBaneiPredictor:
    def test_train_returns_results(self):
        features_df = _make_features_df()
        predictor = BaneiPredictor()
        results = predictor.train(features_df)
        assert "avg_hit_rate" in results
        assert "num_features" in results
        assert results["num_features"] > 0

    def test_predict_returns_rankings(self):
        features_df = _make_features_df()
        predictor = BaneiPredictor()
        predictor.train(features_df)

        predictions = predictor.predict(features_df)
        assert "win_prob" in predictions.columns
        assert "pred_rank" in predictions.columns
        # 各レースに1位が1つだけ存在すること
        for _, race in predictions.groupby(["race_date", "race_no"]):
            assert (race["pred_rank"] == 1).sum() == 1

    def test_save_and_load(self, tmp_path, monkeypatch):
        import config.settings as settings

        monkeypatch.setattr(settings, "MODELS_DIR", tmp_path)

        features_df = _make_features_df()
        predictor = BaneiPredictor()
        predictor.train(features_df)
        predictor.save()

        predictor2 = BaneiPredictor()
        predictor2.load()

        # 同じ予測結果が得られること
        pred1 = predictor.predict(features_df)
        pred2 = predictor2.predict(features_df)
        np.testing.assert_array_almost_equal(
            pred1["win_prob"].values, pred2["win_prob"].values
        )

    def test_feature_importance(self):
        features_df = _make_features_df()
        predictor = BaneiPredictor()
        predictor.train(features_df)

        importance = predictor.get_feature_importance()
        assert len(importance) > 0
        assert "feature" in importance.columns
        assert "importance" in importance.columns
