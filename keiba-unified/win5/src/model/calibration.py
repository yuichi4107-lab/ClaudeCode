"""LightGBM(またはsklearn互換)分類器に確率較正を施すラッパ。

EVは較正後の勝率で計算する方針（spec §6）。学習時に内部CVで較正する。
"""

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV

try:
    from lightgbm import LGBMClassifier
    _BASE = LGBMClassifier
except Exception:  # pragma: no cover - fallback when lightgbm absent
    from sklearn.ensemble import HistGradientBoostingClassifier as _BASE

from config.settings import LIGHTGBM_DEFAULT_PARAMS


class CalibratedWinModel:
    def __init__(self, method: str = "isotonic", params: dict | None = None, cv: int = 3):
        self.method = method
        self.cv = cv
        try:
            self.params = params or LIGHTGBM_DEFAULT_PARAMS.copy()
        except Exception:
            self.params = params or {}
        self.feature_cols: list[str] = []
        self.calibrated: CalibratedClassifierCV | None = None

    def _matrix(self, df: pd.DataFrame, feature_cols: list[str]) -> np.ndarray:
        X = df[feature_cols].values.astype(np.float32)
        return np.nan_to_num(X, nan=0.0, posinf=1e6, neginf=-1e6)

    def fit(self, df: pd.DataFrame, feature_cols: list[str],
            target_col: str = "target") -> "CalibratedWinModel":
        self.feature_cols = feature_cols
        X = self._matrix(df, feature_cols)
        y = df[target_col].values.astype(int)
        # CalibratedClassifierCV は eval_set を渡せないため early_stopping_rounds を除外する
        safe_params = {k: v for k, v in self.params.items() if k != "early_stopping_rounds"}
        try:
            base = _BASE(**safe_params)
        except TypeError:
            base = _BASE()
        self.calibrated = CalibratedClassifierCV(base, method=self.method, cv=self.cv)
        self.calibrated.fit(X, y)
        return self

    def predict_proba(self, df: pd.DataFrame, feature_cols: list[str] | None = None) -> np.ndarray:
        cols = feature_cols or self.feature_cols
        X = self._matrix(df, cols)
        return self.calibrated.predict_proba(X)[:, 1]
