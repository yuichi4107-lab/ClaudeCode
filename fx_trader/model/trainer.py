"""モデル学習 - LightGBM / sklearn による方向予測モデル"""

import logging

import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.impute import SimpleImputer
from sklearn.model_selection import TimeSeriesSplit, cross_val_score
from sklearn.pipeline import Pipeline

from fx_trader.config import settings

logger = logging.getLogger(__name__)

# LightGBM がなければ sklearn にフォールバック
try:
    from lightgbm import LGBMClassifier
    HAS_LGBM = True
except ImportError:
    HAS_LGBM = False


class ModelTrainer:
    """FX方向予測モデルの学習"""

    def __init__(self, model_params: dict = None):
        self.model_params = model_params or settings.MODEL_PARAMS

    def _build_pipeline(self) -> Pipeline:
        """学習パイプラインを構築"""
        if HAS_LGBM:
            clf = LGBMClassifier(
                n_estimators=self.model_params["n_estimators"],
                learning_rate=self.model_params["learning_rate"],
                max_depth=self.model_params["max_depth"],
                min_child_samples=self.model_params["min_child_samples"],
                class_weight=self.model_params["class_weight"],
                random_state=self.model_params["random_state"],
                verbose=-1,
            )
            logger.info("Using LightGBM classifier")
        else:
            from sklearn.ensemble import HistGradientBoostingClassifier
            clf = HistGradientBoostingClassifier(
                max_iter=self.model_params["n_estimators"],
                learning_rate=self.model_params["learning_rate"],
                max_depth=self.model_params["max_depth"],
                min_samples_leaf=self.model_params["min_child_samples"],
                random_state=self.model_params["random_state"],
            )
            logger.info("Using sklearn HistGradientBoostingClassifier (LightGBM not available)")

        return Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("clf", clf),
        ])

    def train(self, X, y, n_splits: int = 5) -> dict:
        """モデルを学習してキャリブレーション

        Args:
            X: 特徴量 DataFrame
            y: ラベル Series (1=上昇, 0=下降)
            n_splits: TimeSeriesSplit の分割数

        Returns:
            dict: {
                "model": キャリブレーション済みモデル,
                "cv_scores": クロスバリデーション ROC-AUC スコア,
                "features": 特徴量名リスト,
                "positive_rate": 正例率,
            }
        """
        logger.info("Training with %d samples, %d features", len(X), X.shape[1])
        logger.info("Positive rate: %.3f", y.mean())

        pipeline = self._build_pipeline()

        # TimeSeriesSplit でクロスバリデーション
        tscv = TimeSeriesSplit(n_splits=n_splits)
        cv_scores = cross_val_score(pipeline, X, y, cv=tscv, scoring="roc_auc", n_jobs=-1)

        logger.info("CV ROC-AUC scores: %s", np.round(cv_scores, 4))
        logger.info("Mean ROC-AUC: %.4f (±%.4f)", cv_scores.mean(), cv_scores.std())

        # 全データで再学習
        pipeline.fit(X, y)

        # 確率キャリブレーション (TimeSeriesSplitで)
        tscv_cal = TimeSeriesSplit(n_splits=n_splits)
        calibrated = CalibratedClassifierCV(pipeline, cv=tscv_cal, method="isotonic")
        calibrated.fit(X, y)

        return {
            "model": calibrated,
            "cv_scores": cv_scores.tolist(),
            "features": list(X.columns),
            "positive_rate": float(y.mean()),
        }
