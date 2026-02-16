import logging
import time

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.impute import SimpleImputer
from sklearn.model_selection import TimeSeriesSplit, cross_val_score
from sklearn.pipeline import Pipeline

logger = logging.getLogger(__name__)

# デフォルトパラメータ (チューニング結果に基づく最適値)
DEFAULT_PARAMS = {
    "n_estimators": 300,
    "learning_rate": 0.03,
    "max_depth": 4,
    "min_child_samples": 20,
    "num_leaves": 31,
    "subsample": 1.0,
    "colsample_bytree": 0.8,
    "reg_alpha": 0.1,
    "reg_lambda": 0.1,
}

# チューニング探索空間
PARAM_GRID = {
    "n_estimators": [200, 300, 500, 800],
    "learning_rate": [0.01, 0.03, 0.05, 0.1],
    "max_depth": [4, 6, 8, -1],
    "min_child_samples": [10, 20, 50],
    "num_leaves": [31, 63, 127],
    "subsample": [0.7, 0.8, 1.0],
    "colsample_bytree": [0.7, 0.8, 1.0],
    "reg_alpha": [0, 0.1, 1.0],
    "reg_lambda": [0, 0.1, 1.0],
}


def _build_base_pipeline(lgbm_params: dict | None = None) -> Pipeline:
    params = lgbm_params or DEFAULT_PARAMS
    try:
        from lightgbm import LGBMClassifier
        clf = LGBMClassifier(
            **params,
            class_weight="balanced",
            random_state=42,
            verbose=-1,
        )
        logger.info("Using LightGBM classifier")
    except ImportError:
        from sklearn.ensemble import HistGradientBoostingClassifier
        clf = HistGradientBoostingClassifier(
            max_iter=params.get("n_estimators", 300),
            learning_rate=params.get("learning_rate", 0.05),
            max_depth=params.get("max_depth", 6),
            min_samples_leaf=params.get("min_child_samples", 20),
            class_weight="balanced",
            random_state=42,
        )
        logger.info("LightGBM not available, using HistGradientBoostingClassifier")

    return Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("clf", clf),
    ])


class ModelTrainer:
    """
    TimeSeriesSplit で未来リークを防ぎながら学習する。
    最終モデルは全データで学習し、Platt スケーリングで確率キャリブレーションを行う。
    """

    def __init__(self, lgbm_params: dict | None = None):
        self.lgbm_params = lgbm_params

    def train(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        n_splits: int = 5,
    ) -> CalibratedClassifierCV:
        pipeline = _build_base_pipeline(self.lgbm_params)

        tscv = TimeSeriesSplit(n_splits=n_splits)
        scores = cross_val_score(
            pipeline, X, y, cv=tscv, scoring="roc_auc", n_jobs=-1
        )
        logger.info(
            "TimeSeriesSplit ROC-AUC: %.3f +/- %.3f", scores.mean(), scores.std()
        )
        print(
            f"Cross-validation ROC-AUC: {scores.mean():.3f} +/- {scores.std():.3f}"
        )

        # 全データで最終学習
        pipeline.fit(X, y)

        # 確率キャリブレーション
        calibrated = CalibratedClassifierCV(pipeline, cv=5, method="isotonic")
        calibrated.fit(X, y)

        return calibrated

    @staticmethod
    def tune(
        X: pd.DataFrame,
        y: pd.Series,
        n_splits: int = 5,
        n_iter: int = 24,
    ) -> tuple[dict, float]:
        """
        ランダムサーチでLightGBMのハイパーパラメータを最適化する。

        Returns: (best_params, best_score)
        """
        from sklearn.model_selection import ParameterSampler

        tscv = TimeSeriesSplit(n_splits=n_splits)

        best_score = -1.0
        best_params = {}
        results = []

        sampler = list(ParameterSampler(PARAM_GRID, n_iter=n_iter, random_state=42))
        total = len(sampler)

        print(f"  ハイパーパラメータ探索: {total} 通り")
        for i, params in enumerate(sampler, 1):
            t0 = time.time()
            pipeline = _build_base_pipeline(params)
            scores = cross_val_score(
                pipeline, X, y, cv=tscv, scoring="roc_auc", n_jobs=-1
            )
            mean_score = scores.mean()
            std_score = scores.std()
            elapsed = time.time() - t0

            results.append({
                "params": params,
                "mean_auc": mean_score,
                "std_auc": std_score,
            })

            marker = " *** BEST" if mean_score > best_score else ""
            print(f"  [{i:2d}/{total}] AUC={mean_score:.4f}±{std_score:.4f} "
                  f"({elapsed:.1f}s){marker}")

            if mean_score > best_score:
                best_score = mean_score
                best_params = dict(params)

        # 上位5件を表示
        results.sort(key=lambda x: x["mean_auc"], reverse=True)
        print(f"\n  Top-5 パラメータ設定:")
        for rank, r in enumerate(results[:5], 1):
            p = r["params"]
            print(f"    {rank}. AUC={r['mean_auc']:.4f} | "
                  f"lr={p.get('learning_rate')}, n_est={p.get('n_estimators')}, "
                  f"depth={p.get('max_depth')}, leaves={p.get('num_leaves')}, "
                  f"sub={p.get('subsample')}, col={p.get('colsample_bytree')}")

        print(f"\n  最適パラメータ: {best_params}")
        print(f"  最高AUC: {best_score:.4f}")

        return best_params, best_score
