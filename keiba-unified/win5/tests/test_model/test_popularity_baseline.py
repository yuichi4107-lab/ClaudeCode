import numpy as np
import pandas as pd

from model.popularity_baseline import PopularityBaseline


def _train_df():
    # 4レース×各2頭。各レースの勝ち馬(target=1)の人気を変えて学習させる
    return pd.DataFrame(
        {
            "_race_id": ["r1", "r1", "r2", "r2", "r3", "r3", "r4", "r4"],
            "popularity": [1, 2, 1, 2, 1, 2, 2, 1],
            "target": [1.0, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 0.0],
        }
    )


def test_fit_and_predict_win_prob_by_popularity():
    bl = PopularityBaseline().fit(_train_df())
    # 学習: 1番人気が勝った回数=3/4=0.75、2番人気=1/4=0.25
    df = pd.DataFrame({"popularity": [1, 2]})
    probs = bl.predict(df)
    assert abs(probs[0] - 0.75) < 1e-6
    assert abs(probs[1] - 0.25) < 1e-6


def test_predict_unknown_rank_returns_small_prob():
    bl = PopularityBaseline().fit(_train_df())
    probs = bl.predict(pd.DataFrame({"popularity": [18]}))
    assert 0.0 <= probs[0] <= 1.0
