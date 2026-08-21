import numpy as np
import pandas as pd

from model.calibration import CalibratedWinModel


def _toy(n=400):
    rng = np.random.RandomState(0)
    x = rng.rand(n)
    # 真の確率は x に単調。target をベルヌーイ生成
    p = x * 0.6
    y = (rng.rand(n) < p).astype(float)
    return pd.DataFrame({"f1": x, "target": y, "_race_date": ["2024-01-01"] * n})


def test_calibrated_probs_are_valid_and_predict_proba_shape():
    df = _toy()
    m = CalibratedWinModel(method="isotonic").fit(df, feature_cols=["f1"])
    probs = m.predict_proba(df, feature_cols=["f1"])
    assert probs.shape == (len(df),)
    assert float(probs.min()) >= 0.0
    assert float(probs.max()) <= 1.0


def test_calibration_does_not_worsen_brier_much_vs_raw():
    from sklearn.metrics import brier_score_loss

    df = _toy()
    m = CalibratedWinModel(method="isotonic").fit(df, feature_cols=["f1"])
    probs = m.predict_proba(df, feature_cols=["f1"])
    brier = brier_score_loss(df["target"].values, probs)
    # ベース率予測(全部平均)のBrierより良い
    base = brier_score_loss(df["target"].values, np.full(len(df), df["target"].mean()))
    assert brier <= base + 1e-9
