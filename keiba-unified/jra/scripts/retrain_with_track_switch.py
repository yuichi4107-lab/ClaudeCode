"""トラック替わり特徴量を含めたモデル再学習スクリプト

Step 1: FastFeaturePipelineで特徴量再構築（新5特徴量含む）
Step 2: LightGBMモデル再学習
Step 3: 特徴量重要度の確認
"""

import os
import sys
import time

import joblib
import numpy as np
import pandas as pd

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)

from src.features.fast_pipeline import FastFeaturePipeline
from src.models.lgbm_model import LGBMModel
from src.models.probability_calibrator import ProbabilityCalibrator
from src.utils.config_loader import load_backtest_config
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

DB_PATH = os.path.join(PROJECT_ROOT, "data", "keiba.db")
FEATURES_PATH = os.path.join(PROJECT_ROOT, "data", "features.csv")
MODEL_DIR = os.path.join(PROJECT_ROOT, "data", "models")


def build_features():
    """FastFeaturePipelineで特徴量を再構築"""
    logger.info("=== Step 1: 特徴量再構築 ===")
    pipeline = FastFeaturePipeline(DB_PATH)

    start = time.time()
    # 2021-01-01 から 2024-12-31 まで (2025年はデータ欠損多いため除外)
    df = pipeline.build_features("2021-01-01", "2024-12-31")
    elapsed = time.time() - start

    # target列を追加（3着以内=1, それ以外=0）
    df["target"] = (df["finish_order"] <= 3).astype(int)
    # finish_orderをfinish_positionにリネーム（backtest engine互換）
    df = df.rename(columns={"finish_order": "finish_position"})

    logger.info("特徴量構築完了: %d行 x %d列 (%.1f秒)", len(df), len(df.columns), elapsed)

    # 新特徴量の統計を表示
    track_cols = ["is_first_dirt", "is_first_turf", "career_at_switch",
                  "prev_surface_runs", "prev_weight_for_switch"]
    logger.info("--- 新特徴量の統計 ---")
    for col in track_cols:
        if col in df.columns:
            logger.info("  %s: mean=%.3f, max=%.1f, non-zero=%d",
                        col, df[col].mean(), df[col].max(),
                        (df[col] != 0).sum())

    # 保存
    df.to_csv(FEATURES_PATH, index=False, encoding="utf-8-sig")
    logger.info("保存: %s", FEATURES_PATH)
    return df


def train_model(features_df):
    """LightGBMモデルを再学習"""
    logger.info("=== Step 2: モデル再学習 ===")
    config = load_backtest_config()

    # データ分割
    train_mask = features_df["race_date"] <= "2023-12-31"
    val_mask = (features_df["race_date"] >= "2024-01-01") & (features_df["race_date"] <= "2024-12-31")

    meta_cols = {"race_id", "race_date", "horse_number", "horse_id",
                 "horse_name", "finish_position", "target"}
    feature_cols = [c for c in features_df.columns if c not in meta_cols]

    X_train = features_df.loc[train_mask, feature_cols]
    y_train = features_df.loc[train_mask, "target"]
    X_val = features_df.loc[val_mask, feature_cols]
    y_val = features_df.loc[val_mask, "target"]

    logger.info("Train: %d行, Val: %d行, 特徴量: %d", len(X_train), len(X_val), len(feature_cols))

    # 学習
    model = LGBMModel()
    model.fit(X_train, y_train, X_val, y_val)

    # キャリブレーション
    logger.info("確率キャリブレーション...")
    val_proba = model.predict_proba(X_val)

    calibrator = ProbabilityCalibrator(method="isotonic")
    calibrator.fit(y_val.values, val_proba)

    calibrated = calibrator.calibrate(val_proba)

    brier_raw = ProbabilityCalibrator.brier_score(y_val.values, val_proba)
    brier_cal = ProbabilityCalibrator.brier_score(y_val.values, calibrated)
    ece_raw = ProbabilityCalibrator.expected_calibration_error(y_val.values, val_proba)
    ece_cal = ProbabilityCalibrator.expected_calibration_error(y_val.values, calibrated)

    logger.info("Brier Score - Raw: %.4f, Calibrated: %.4f", brier_raw, brier_cal)
    logger.info("ECE         - Raw: %.4f, Calibrated: %.4f", ece_raw, ece_cal)

    # 保存
    os.makedirs(MODEL_DIR, exist_ok=True)
    model_path = os.path.join(MODEL_DIR, "lgbm_model.joblib")
    model.save(model_path)

    calibrator_path = os.path.join(MODEL_DIR, "calibrator.joblib")
    joblib.dump(calibrator, calibrator_path)
    logger.info("モデル保存: %s", model_path)

    # 特徴量重要度
    logger.info("=== Step 3: 特徴量重要度 (Top 30) ===")
    importance = model.get_feature_importance_dict(feature_cols)
    for i, (name, imp) in enumerate(list(importance.items())[:30]):
        marker = " ★NEW" if name in ("is_first_dirt", "is_first_turf",
                                      "career_at_switch", "prev_surface_runs",
                                      "prev_weight_for_switch") else ""
        logger.info("  %2d. %-40s %d%s", i + 1, name, imp, marker)

    # 新特徴量の重要度をピックアップ
    logger.info("\n--- 新特徴量の重要度 ---")
    track_features = ["is_first_dirt", "is_first_turf", "career_at_switch",
                      "prev_surface_runs", "prev_weight_for_switch"]
    for feat in track_features:
        imp_val = importance.get(feat, 0)
        rank = list(importance.keys()).index(feat) + 1 if feat in importance else "N/A"
        logger.info("  %s: importance=%d, rank=%s/%d", feat, imp_val, rank, len(importance))

    return model, calibrator


def main():
    logger.info("トラック替わり特徴量を含めたモデル再学習を開始")

    # Step 1: 特徴量構築
    features_df = build_features()

    # Step 2-3: モデル学習 + 重要度確認
    model, calibrator = train_model(features_df)

    logger.info("再学習完了")


if __name__ == "__main__":
    main()
