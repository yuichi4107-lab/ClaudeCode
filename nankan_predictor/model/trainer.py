import logging

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.impute import SimpleImputer
from sklearn.model_selection import TimeSeriesSplit, cross_val_score
from sklearn.pipeline import Pipeline

logger = logging.getLogger(__name__)


def _build_base_pipeline() -> Pipeline:
    try:
        from lightgbm import LGBMClassifier
        clf = LGBMClassifier(
            n_estimators=300,
            learning_rate=0.05,
            max_depth=6,
            min_child_samples=20,
            class_weight="balanced",
            random_state=42,
            verbose=-1,
        )
        logger.info("Using LightGBM classifier")
    except ImportError:
        from sklearn.ensemble import HistGradientBoostingClassifier
        clf = HistGradientBoostingClassifier(
            max_iter=300,
            learning_rate=0.05,
            max_depth=6,
            min_samples_leaf=20,
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

    def train(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        n_splits: int = 5,
    ) -> CalibratedClassifierCV:
        pipeline = _build_base_pipeline()

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
