"""モデル学習スクリプト

Usage:
    python -m scripts.03_train_model
"""

import os
import sys

import pandas as pd

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.backtest.data_splitter import DataSplitter
from src.models.lgbm_model import LGBMModel
from src.models.probability_calibrator import ProbabilityCalibrator
from src.utils.config_loader import get_project_root, load_backtest_config
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


def main():
    project_root = get_project_root()
    config = load_backtest_config()

    # ------------------------------------------------------------------
    # 1. Load features
    # ------------------------------------------------------------------
    features_path = os.path.join(project_root, "data", "features.parquet")
    if not os.path.exists(features_path):
        logger.error("Feature file not found: %s", features_path)
        logger.info("Run scripts/02_build_features.py first.")
        sys.exit(1)

    logger.info("Loading features from %s", features_path)
    features_df = pd.read_parquet(features_path)
    logger.info("Features shape: %s", features_df.shape)

    # ------------------------------------------------------------------
    # 2. Split data
    # ------------------------------------------------------------------
    splitter = DataSplitter(config)
    train_idx, val_idx, test_idx = splitter.train_val_test_split(
        features_df["race_date"]
    )
    logger.info("Train: %d, Val: %d, Test: %d", len(train_idx), len(val_idx), len(test_idx))

    # ------------------------------------------------------------------
    # 3. Identify feature columns
    # ------------------------------------------------------------------
    meta_cols = {"race_id", "race_date", "horse_number", "horse_id",
                 "finish_position", "target"}
    feature_cols = [c for c in features_df.columns if c not in meta_cols]
    logger.info("Feature columns: %d", len(feature_cols))

    X_train = features_df.loc[train_idx, feature_cols]
    y_train = features_df.loc[train_idx, "target"]
    X_val = features_df.loc[val_idx, feature_cols]
    y_val = features_df.loc[val_idx, "target"]

    # ------------------------------------------------------------------
    # 4. Train LightGBM model
    # ------------------------------------------------------------------
    logger.info("Training LightGBM model...")
    model = LGBMModel()
    model.fit(X_train, y_train, X_val, y_val)

    # ------------------------------------------------------------------
    # 5. Calibrate probabilities
    # ------------------------------------------------------------------
    logger.info("Calibrating probabilities...")
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

    # ------------------------------------------------------------------
    # 6. Save model and calibrator
    # ------------------------------------------------------------------
    model_dir = os.path.join(project_root, "data", "models")
    os.makedirs(model_dir, exist_ok=True)

    model_path = os.path.join(model_dir, "lgbm_model.joblib")
    model.save(model_path)

    import joblib
    calibrator_path = os.path.join(model_dir, "calibrator.joblib")
    joblib.dump(calibrator, calibrator_path)
    logger.info("Calibrator saved to %s", calibrator_path)

    # ------------------------------------------------------------------
    # 7. Print feature importances (top 30)
    # ------------------------------------------------------------------
    importance = model.get_feature_importance_dict(feature_cols)
    logger.info("--- Top 30 Feature Importances ---")
    for i, (name, imp) in enumerate(list(importance.items())[:30]):
        logger.info("  %2d. %-40s %d", i + 1, name, imp)

    logger.info("Training complete.")


if __name__ == "__main__":
    main()
