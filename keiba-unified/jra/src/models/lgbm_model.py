"""LightGBMモデル"""

import os

import joblib
import lightgbm as lgb
import numpy as np

from src.models.base_model import BaseModel
from src.utils.config_loader import load_backtest_config
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class LGBMModel(BaseModel):
    """LightGBM binary classifier for top-3 finish prediction."""

    def __init__(self, params: dict = None):
        config = load_backtest_config()
        default_params = config["model"]["params"]

        if params is not None:
            default_params.update(params)

        self._early_stopping_rounds = default_params.pop(
            "early_stopping_rounds", 50
        )
        self.params = default_params
        self.model = lgb.LGBMClassifier(**self.params)
        self._is_fitted = False

    def fit(self, X, y, X_val=None, y_val=None):
        """Train with optional early stopping on validation set."""
        callbacks = [lgb.log_evaluation(period=100)]

        if X_val is not None and y_val is not None:
            callbacks.append(
                lgb.early_stopping(
                    stopping_rounds=self._early_stopping_rounds,
                    verbose=True,
                )
            )
            self.model.fit(
                X,
                y,
                eval_set=[(X_val, y_val)],
                callbacks=callbacks,
            )
        else:
            self.model.fit(X, y, callbacks=callbacks)

        self._is_fitted = True
        logger.info(
            "Model trained: best_iteration=%s",
            getattr(self.model, "best_iteration_", "N/A"),
        )

    def predict_proba(self, X) -> np.ndarray:
        """Return probability of top-3 finish (positive class)."""
        proba = self.model.predict_proba(X)
        return proba[:, 1]

    def save(self, path: str):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        joblib.dump(
            {
                "model": self.model,
                "params": self.params,
                "early_stopping_rounds": self._early_stopping_rounds,
            },
            path,
        )
        logger.info("Model saved to %s", path)

    def load(self, path: str):
        data = joblib.load(path)
        self.model = data["model"]
        self.params = data["params"]
        self._early_stopping_rounds = data["early_stopping_rounds"]
        self._is_fitted = True
        logger.info("Model loaded from %s", path)

    @property
    def feature_importances_(self) -> np.ndarray:
        return self.model.feature_importances_

    def get_feature_importance_dict(self, feature_names: list) -> dict:
        """Return {feature_name: importance} sorted descending."""
        importances = self.feature_importances_
        pairs = sorted(
            zip(feature_names, importances), key=lambda x: x[1], reverse=True
        )
        return dict(pairs)
