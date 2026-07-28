"""LightGBMによるばんえい競馬単勝予測モデル"""

from __future__ import annotations

import logging
from pathlib import Path

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.model_selection import TimeSeriesSplit

from config.settings import LIGHTGBM_PARAMS, MODELS_DIR

logger = logging.getLogger(__name__)

# モデルに使用する特徴量カラム
FEATURE_COLUMNS = [
    "post_position",
    "horse_weight",
    "weight_carry",
    "age",
    "sex_code",
    "distance",
    "num_runners",
    "post_position_norm",
    "month",
    "past_runs",
    "past_win_rate",
    "past_top3_rate",
    "past_avg_finish",
    "past_best_finish",
    "past_avg_time",
    "past_best_time",
    "days_since_last_race",
    "jockey_win_rate",
    "jockey_top3_rate",
    "trainer_win_rate",
    "trainer_top3_rate",
    "weight_rank_in_race",
    "weight_diff_from_mean",
    "carry_rank_in_race",
    "carry_to_weight_ratio",
]

TARGET_COLUMN = "is_win"


class BaneiPredictor:
    """ばんえい競馬単勝予測モデル"""

    def __init__(self):
        self.model: lgb.LGBMClassifier | None = None
        self.feature_columns = FEATURE_COLUMNS
        MODELS_DIR.mkdir(parents=True, exist_ok=True)

    def train(self, df: pd.DataFrame) -> dict:
        """モデルを学習する

        Returns:
            学習結果の評価指標
        """
        df = df.dropna(subset=[TARGET_COLUMN])

        available_features = [c for c in self.feature_columns if c in df.columns]
        if not available_features:
            raise ValueError("使用可能な特徴量がありません")

        self.feature_columns = available_features
        X = df[available_features].copy()
        y = df[TARGET_COLUMN].copy()

        logger.info("学習データ: %d 件, 特徴量: %d 個", len(X), len(available_features))
        logger.info("正例率: %.3f", y.mean())

        # 時系列分割でクロスバリデーション
        tscv = TimeSeriesSplit(n_splits=5)
        scores = []

        for fold, (train_idx, val_idx) in enumerate(tscv.split(X)):
            X_train, X_val = X.iloc[train_idx], X.iloc[val_idx]
            y_train, y_val = y.iloc[train_idx], y.iloc[val_idx]

            model = lgb.LGBMClassifier(**LIGHTGBM_PARAMS)
            model.fit(
                X_train,
                y_train,
                eval_set=[(X_val, y_val)],
            )

            val_pred = model.predict_proba(X_val)[:, 1]

            # レース単位での的中率を計算
            val_data = df.iloc[val_idx][["race_date", "race_no", TARGET_COLUMN]].copy()
            val_data["pred_prob"] = val_pred
            hit_rate = self._calc_hit_rate(val_data)
            scores.append(hit_rate)
            logger.info("Fold %d: 的中率 = %.3f", fold + 1, hit_rate)

        # 全データで最終モデルを学習（early stoppingは無効化）
        final_params = {
            k: v
            for k, v in LIGHTGBM_PARAMS.items()
            if k != "early_stopping_rounds"
        }
        self.model = lgb.LGBMClassifier(**final_params)
        self.model.fit(X, y)

        results = {
            "avg_hit_rate": np.mean(scores),
            "std_hit_rate": np.std(scores),
            "num_features": len(available_features),
            "num_samples": len(X),
        }

        logger.info(
            "平均的中率: %.3f (+/- %.3f)", results["avg_hit_rate"], results["std_hit_rate"]
        )

        return results

    @staticmethod
    def _calc_hit_rate(val_data: pd.DataFrame) -> float:
        """レース単位での単勝的中率を計算"""
        correct = 0
        total = 0

        for _, race in val_data.groupby(["race_date", "race_no"]):
            if race[TARGET_COLUMN].sum() == 0:
                continue
            total += 1
            top_pred_idx = race["pred_prob"].idxmax()
            if race.loc[top_pred_idx, TARGET_COLUMN] == 1:
                correct += 1

        return correct / total if total > 0 else 0.0

    def predict(self, df: pd.DataFrame) -> pd.DataFrame:
        """予測を行い、各馬の勝率を返す"""
        if self.model is None:
            raise RuntimeError("モデルが学習されていません。先にtrain()を実行してください。")

        available_features = [c for c in self.feature_columns if c in df.columns]
        X = df[available_features].copy()
        probs = self.model.predict_proba(X)[:, 1]

        result = df[["race_date", "race_no", "horse_number", "horse_name"]].copy()
        result["win_prob"] = probs

        # レースごとに確率を正規化して予想順位を付与
        result["pred_rank"] = result.groupby(["race_date", "race_no"])[
            "win_prob"
        ].rank(ascending=False, method="min")

        result = result.sort_values(
            ["race_date", "race_no", "pred_rank"]
        ).reset_index(drop=True)

        return result

    def get_feature_importance(self) -> pd.DataFrame:
        """特徴量重要度を返す"""
        if self.model is None:
            raise RuntimeError("モデルが学習されていません")

        importance = pd.DataFrame(
            {
                "feature": self.feature_columns,
                "importance": self.model.feature_importances_,
            }
        )
        importance = importance.sort_values("importance", ascending=False)
        return importance

    def save(self, filename: str = "banei_model.pkl"):
        """モデルを保存する"""
        if self.model is None:
            raise RuntimeError("モデルが学習されていません")

        filepath = MODELS_DIR / filename
        data = {
            "model": self.model,
            "feature_columns": self.feature_columns,
        }
        joblib.dump(data, filepath)
        logger.info("モデル保存完了: %s", filepath)
        return filepath

    def load(self, filename: str = "banei_model.pkl"):
        """保存済みモデルを読み込む"""
        filepath = MODELS_DIR / filename
        if not filepath.exists():
            raise FileNotFoundError(f"モデルファイルが見つかりません: {filepath}")

        data = joblib.load(filepath)
        self.model = data["model"]
        self.feature_columns = data["feature_columns"]
        logger.info("モデル読み込み完了: %s", filepath)
