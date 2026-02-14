"""評価指標・SHAP分析"""

import logging
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    brier_score_loss,
    log_loss,
    precision_score,
    recall_score,
    roc_auc_score,
)

logger = logging.getLogger(__name__)


def compute_metrics(y_true: np.ndarray, y_pred_proba: np.ndarray) -> dict[str, float]:
    """予測結果の評価指標を計算する"""
    y_true = np.asarray(y_true)
    y_pred_proba = np.asarray(y_pred_proba)

    # 二値予測(閾値=0.5ではなく各レースtop1を正とする方が現実的だが、一般指標用)
    y_pred_binary = (y_pred_proba >= 0.5).astype(int)

    metrics: dict[str, float] = {}

    try:
        metrics["auc"] = float(roc_auc_score(y_true, y_pred_proba))
    except ValueError:
        metrics["auc"] = 0.5

    metrics["logloss"] = float(log_loss(y_true, y_pred_proba, eps=1e-7))
    metrics["brier"] = float(brier_score_loss(y_true, y_pred_proba))
    metrics["accuracy"] = float(accuracy_score(y_true, y_pred_binary))

    try:
        metrics["precision"] = float(precision_score(y_true, y_pred_binary, zero_division=0))
        metrics["recall"] = float(recall_score(y_true, y_pred_binary, zero_division=0))
    except Exception:
        metrics["precision"] = 0.0
        metrics["recall"] = 0.0

    return metrics


def compute_race_level_metrics(
    df: pd.DataFrame,
    prob_col: str = "calibrated_prob",
    actual_col: str = "_finish_position",
) -> dict[str, float]:
    """レース単位の評価指標を計算する

    - Top1的中率: 予測1位が実際の1着かどうか
    - Top3的中率: 予測上位3頭に1着馬が含まれるか
    """
    if df.empty:
        return {"top1_hit_rate": 0.0, "top3_hit_rate": 0.0, "avg_winner_rank": 10.0}

    top1_hits = 0
    top3_hits = 0
    winner_ranks = []
    total_races = 0

    for race_id, group in df.groupby("_race_id"):
        if prob_col not in group.columns or actual_col not in group.columns:
            continue

        sorted_group = group.sort_values(prob_col, ascending=False).reset_index(drop=True)
        winner_mask = sorted_group[actual_col] == 1

        if not winner_mask.any():
            continue

        total_races += 1
        winner_rank = sorted_group.index[winner_mask].min() + 1
        winner_ranks.append(winner_rank)

        if winner_rank == 1:
            top1_hits += 1
        if winner_rank <= 3:
            top3_hits += 1

    if total_races == 0:
        return {"top1_hit_rate": 0.0, "top3_hit_rate": 0.0, "avg_winner_rank": 10.0}

    return {
        "top1_hit_rate": top1_hits / total_races,
        "top3_hit_rate": top3_hits / total_races,
        "avg_winner_rank": float(np.mean(winner_ranks)),
        "total_races": total_races,
    }


def shap_analysis(
    model,
    X: np.ndarray,
    feature_names: list[str],
    max_samples: int = 1000,
) -> pd.DataFrame:
    """SHAP値による特徴量重要度分析"""
    try:
        import shap
    except ImportError:
        logger.warning("SHAP not installed. Skipping SHAP analysis.")
        return pd.DataFrame()

    if len(X) > max_samples:
        idx = np.random.choice(len(X), max_samples, replace=False)
        X_sample = X[idx]
    else:
        X_sample = X

    explainer = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(X_sample)

    # LightGBM binary: shap_values は [neg_class, pos_class] のリスト
    if isinstance(shap_values, list):
        sv = shap_values[1]  # positive class
    else:
        sv = shap_values

    mean_abs_shap = np.abs(sv).mean(axis=0)
    df = pd.DataFrame(
        {"feature": feature_names, "mean_abs_shap": mean_abs_shap}
    )
    df = df.sort_values("mean_abs_shap", ascending=False).reset_index(drop=True)

    return df


def calibration_check(
    y_true: np.ndarray, y_pred_proba: np.ndarray, n_bins: int = 10
) -> pd.DataFrame:
    """キャリブレーション(確率の信頼性)を検証する"""
    bins = np.linspace(0, 1, n_bins + 1)
    rows = []

    for i in range(n_bins):
        mask = (y_pred_proba >= bins[i]) & (y_pred_proba < bins[i + 1])
        if mask.sum() == 0:
            continue
        rows.append(
            {
                "bin_start": bins[i],
                "bin_end": bins[i + 1],
                "mean_predicted": float(y_pred_proba[mask].mean()),
                "mean_actual": float(y_true[mask].mean()),
                "count": int(mask.sum()),
            }
        )

    return pd.DataFrame(rows)
