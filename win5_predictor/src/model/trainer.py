"""LightGBMモデルの学習 (時系列CV対応)"""

import json
import logging
import pickle
from datetime import date, datetime, timedelta
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.model_selection import TimeSeriesSplit

from config.settings import (
    CV_GAP_DAYS,
    CV_N_SPLITS,
    CV_TEST_MONTHS,
    LIGHTGBM_DEFAULT_PARAMS,
    MODELS_DIR,
)

logger = logging.getLogger(__name__)


class LightGBMTrainer:
    """LightGBM二値分類モデルの学習"""

    def __init__(self, params: dict | None = None):
        self.params = params or LIGHTGBM_DEFAULT_PARAMS.copy()
        self.model: lgb.LGBMClassifier | None = None
        self.feature_names: list[str] = []
        self.cv_results: list[dict] = []

    def train(
        self,
        df: pd.DataFrame,
        feature_cols: list[str] | None = None,
        target_col: str = "target",
    ) -> lgb.LGBMClassifier:
        """全データで学習する"""
        feature_cols = feature_cols or self._get_feature_cols(df, target_col)
        self.feature_names = feature_cols

        X = df[feature_cols].values.astype(np.float32)
        y = df[target_col].values.astype(np.float32)

        # NaN/inf補正
        X = np.nan_to_num(X, nan=0.0, posinf=1e6, neginf=-1e6)

        logger.info("Training: %d samples, %d features", X.shape[0], X.shape[1])

        self.model = lgb.LGBMClassifier(**self.params)
        self.model.fit(
            X,
            y,
            eval_set=[(X, y)],
            callbacks=[lgb.log_evaluation(period=100)],
        )

        return self.model

    def train_with_timeseries_cv(
        self,
        df: pd.DataFrame,
        date_col: str = "_race_date",
        feature_cols: list[str] | None = None,
        target_col: str = "target",
        n_splits: int = CV_N_SPLITS,
    ) -> lgb.LGBMClassifier:
        """時系列CVで学習・評価し、最終モデルを返す"""
        feature_cols = feature_cols or self._get_feature_cols(df, target_col)
        self.feature_names = feature_cols

        # 日付でソート
        df = df.sort_values(date_col).reset_index(drop=True)
        dates = pd.to_datetime(df[date_col])

        X = df[feature_cols].values.astype(np.float32)
        y = df[target_col].values.astype(np.float32)
        X = np.nan_to_num(X, nan=0.0, posinf=1e6, neginf=-1e6)

        # Walk-forward CV
        self.cv_results = []
        unique_dates = sorted(dates.unique())
        total_dates = len(unique_dates)
        split_size = total_dates // (n_splits + 1)

        for fold in range(n_splits):
            train_end_idx = split_size * (fold + 1)
            train_end_date = unique_dates[min(train_end_idx, total_dates - 1)]

            gap_date = train_end_date + pd.Timedelta(days=CV_GAP_DAYS)
            test_end_date = gap_date + pd.Timedelta(days=CV_TEST_MONTHS * 30)

            train_mask = dates <= train_end_date
            test_mask = (dates > gap_date) & (dates <= test_end_date)

            if test_mask.sum() == 0:
                continue

            X_train, y_train = X[train_mask], y[train_mask]
            X_test, y_test = X[test_mask], y[test_mask]

            model = lgb.LGBMClassifier(**self.params)
            model.fit(
                X_train,
                y_train,
                eval_set=[(X_test, y_test)],
                callbacks=[lgb.log_evaluation(period=0), lgb.early_stopping(50)],
            )

            y_pred = model.predict_proba(X_test)[:, 1]

            from model.evaluation import compute_metrics

            metrics = compute_metrics(y_test, y_pred)
            metrics["fold"] = fold
            metrics["train_size"] = int(train_mask.sum())
            metrics["test_size"] = int(test_mask.sum())
            self.cv_results.append(metrics)

            logger.info(
                "Fold %d: AUC=%.4f, LogLoss=%.4f (train=%d, test=%d)",
                fold,
                metrics["auc"],
                metrics["logloss"],
                metrics["train_size"],
                metrics["test_size"],
            )

        # 全データで最終モデル学習
        self.model = lgb.LGBMClassifier(**self.params)
        self.model.fit(
            X,
            y,
            eval_set=[(X, y)],
            callbacks=[lgb.log_evaluation(period=100)],
        )

        avg_auc = np.mean([r["auc"] for r in self.cv_results]) if self.cv_results else 0.0
        logger.info("Final model trained. CV avg AUC=%.4f", avg_auc)

        return self.model

    def save(self, path: str | Path | None = None, version: str = "") -> Path:
        """モデルを保存する"""
        if self.model is None:
            raise RuntimeError("No model to save. Train first.")

        if not version:
            version = datetime.now().strftime("%Y%m%d_%H%M%S")

        if path is None:
            path = MODELS_DIR / f"lgbm_{version}.pkl"
        else:
            path = Path(path)

        path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "model": self.model,
            "feature_names": self.feature_names,
            "params": self.params,
            "cv_results": self.cv_results,
            "version": version,
            "created_at": datetime.now().isoformat(),
        }

        with open(path, "wb") as f:
            pickle.dump(data, f)

        logger.info("Model saved: %s", path)
        return path

    @classmethod
    def load(cls, path: str | Path) -> "LightGBMTrainer":
        """モデルを読み込む"""
        with open(path, "rb") as f:
            data = pickle.load(f)

        trainer = cls(params=data.get("params", {}))
        trainer.model = data["model"]
        trainer.feature_names = data.get("feature_names", [])
        trainer.cv_results = data.get("cv_results", [])
        return trainer

    def feature_importance(self, top_n: int = 30) -> pd.DataFrame:
        """特徴量の重要度を返す"""
        if self.model is None:
            return pd.DataFrame()

        importance = self.model.feature_importances_
        names = self.feature_names or [f"f{i}" for i in range(len(importance))]

        df = pd.DataFrame({"feature": names, "importance": importance})
        df = df.sort_values("importance", ascending=False).head(top_n)
        return df.reset_index(drop=True)

    def _get_feature_cols(self, df: pd.DataFrame, target_col: str) -> list[str]:
        """特徴量カラムを自動検出(メタカラム・target除外)"""
        exclude = {target_col} | {c for c in df.columns if c.startswith("_")}
        return [c for c in df.columns if c not in exclude]
