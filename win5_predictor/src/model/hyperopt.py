"""Optunaによるハイパーパラメータ最適化"""

import logging

import lightgbm as lgb
import numpy as np
import optuna
import pandas as pd
from sklearn.metrics import log_loss, roc_auc_score

from config.settings import LIGHTGBM_DEFAULT_PARAMS

logger = logging.getLogger(__name__)

# Optunaのログレベルを抑制
optuna.logging.set_verbosity(optuna.logging.WARNING)


class HyperOptimizer:
    """LightGBMのハイパーパラメータをOptunaで最適化する"""

    def __init__(self):
        self.best_params: dict = {}
        self.study: optuna.Study | None = None

    def optimize(
        self,
        df: pd.DataFrame,
        feature_cols: list[str],
        target_col: str = "target",
        date_col: str = "_race_date",
        n_trials: int = 50,
        n_cv_splits: int = 3,
    ) -> dict:
        """ハイパーパラメータの最適化を実行する"""
        df = df.sort_values(date_col).reset_index(drop=True)
        dates = pd.to_datetime(df[date_col])

        X = df[feature_cols].values.astype(np.float32)
        y = df[target_col].values.astype(np.float32)
        X = np.nan_to_num(X, nan=0.0, posinf=1e6, neginf=-1e6)

        # CV分割を事前に定義
        unique_dates = sorted(dates.unique())
        total_dates = len(unique_dates)
        split_size = total_dates // (n_cv_splits + 1)

        cv_splits = []
        for fold in range(n_cv_splits):
            train_end_idx = split_size * (fold + 1)
            train_end_date = unique_dates[min(train_end_idx, total_dates - 1)]
            gap_date = train_end_date + pd.Timedelta(days=7)
            test_end_date = gap_date + pd.Timedelta(days=90)

            train_mask = dates <= train_end_date
            test_mask = (dates > gap_date) & (dates <= test_end_date)

            if test_mask.sum() > 0:
                train_idx = np.where(train_mask)[0]
                test_idx = np.where(test_mask)[0]
                cv_splits.append((train_idx, test_idx))

        if not cv_splits:
            raise ValueError("No valid CV splits found")

        def objective(trial: optuna.Trial) -> float:
            params = {
                "objective": "binary",
                "metric": "binary_logloss",
                "boosting_type": "gbdt",
                "verbose": -1,
                "num_leaves": trial.suggest_int("num_leaves", 15, 127),
                "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.2, log=True),
                "feature_fraction": trial.suggest_float("feature_fraction", 0.5, 1.0),
                "bagging_fraction": trial.suggest_float("bagging_fraction", 0.5, 1.0),
                "bagging_freq": trial.suggest_int("bagging_freq", 1, 10),
                "min_child_samples": trial.suggest_int("min_child_samples", 5, 100),
                "reg_alpha": trial.suggest_float("reg_alpha", 1e-4, 10.0, log=True),
                "reg_lambda": trial.suggest_float("reg_lambda", 1e-4, 10.0, log=True),
                "max_depth": trial.suggest_int("max_depth", 3, 12),
                "n_estimators": 500,
                "early_stopping_rounds": 50,
                "is_unbalance": True,
            }

            scores = []
            for train_idx, test_idx in cv_splits:
                model = lgb.LGBMClassifier(**params)
                model.fit(
                    X[train_idx],
                    y[train_idx],
                    eval_set=[(X[test_idx], y[test_idx])],
                    callbacks=[lgb.log_evaluation(period=0), lgb.early_stopping(50)],
                )
                y_pred = model.predict_proba(X[test_idx])[:, 1]
                score = log_loss(y[test_idx], y_pred, eps=1e-7)
                scores.append(score)

            return float(np.mean(scores))

        self.study = optuna.create_study(direction="minimize")
        self.study.optimize(objective, n_trials=n_trials, show_progress_bar=True)

        self.best_params = {**LIGHTGBM_DEFAULT_PARAMS, **self.study.best_params}
        logger.info(
            "Optimization complete: best logloss=%.4f", self.study.best_value
        )
        logger.info("Best params: %s", self.best_params)

        return self.best_params

    def get_optimization_history(self) -> pd.DataFrame:
        """最適化の履歴をDataFrameで返す"""
        if self.study is None:
            return pd.DataFrame()

        rows = []
        for trial in self.study.trials:
            row = {"trial": trial.number, "value": trial.value}
            row.update(trial.params)
            rows.append(row)

        return pd.DataFrame(rows)
