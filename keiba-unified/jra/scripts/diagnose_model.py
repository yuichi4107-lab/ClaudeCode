"""モデル品質診断・戦略パラメータ最適化

高速パイプラインで特徴量を生成し、モデルの精度を診断する。
"""

import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score, brier_score_loss

from src.features.fast_pipeline import FastFeaturePipeline
from src.models.lgbm_model import LGBMModel
from src.models.probability_calibrator import ProbabilityCalibrator
from src.utils.config_loader import get_db_path


def main():
    db_path = get_db_path()

    # ====== Phase 1: 高速特徴量生成 ======
    print("=" * 60)
    print("Phase 1: Building features (fast pipeline)...")
    print("=" * 60)

    t0 = time.time()
    pipeline = FastFeaturePipeline(db_path)
    df = pipeline.build_features("2021-01-01", "2025-12-31")
    elapsed = time.time() - t0
    print(f"Feature matrix: {df.shape} in {elapsed:.1f}s")

    if df.empty:
        print("ERROR: No features generated")
        return

    # Target
    df["target"] = (df["finish_order"] <= 3).astype(int)
    print(f"Target rate: {df['target'].mean():.3f}")

    # ====== Phase 2: Train/Test Split ======
    print("\n" + "=" * 60)
    print("Phase 2: Train/Test Split")
    print("=" * 60)

    dates = pd.to_datetime(df["race_date"])
    # Train: ~2024-06, Test: 2024-07~
    train_mask = dates <= "2024-06-30"
    test_mask = dates > "2024-06-30"

    n_train = train_mask.sum()
    n_test = test_mask.sum()
    print(f"Train: {n_train} rows, Test: {n_test} rows")

    if n_test < 50:
        # Fallback: 80/20 split
        print("Not enough test data, using 80/20 split")
        split_idx = int(len(df) * 0.8)
        train_mask = pd.Series([True] * split_idx + [False] * (len(df) - split_idx))
        test_mask = ~train_mask
        n_train = train_mask.sum()
        n_test = test_mask.sum()
        print(f"Train: {n_train} rows, Test: {n_test} rows")

    meta_cols = {"race_id", "race_date", "horse_number", "horse_id",
                 "horse_name", "finish_order", "target", "pred_proba"}
    feature_cols = [c for c in df.columns if c not in meta_cols]
    print(f"Feature count: {len(feature_cols)}")
    print(f"Features: {feature_cols}")

    train_df = df[train_mask]
    test_df = df[test_mask].copy()

    X_train = train_df[feature_cols].fillna(0)
    y_train = train_df["target"]
    X_test = test_df[feature_cols].fillna(0)
    y_test = test_df["target"]

    # ====== Phase 3: Model Training ======
    print("\n" + "=" * 60)
    print("Phase 3: Model Training")
    print("=" * 60)

    model = LGBMModel(params={
        "n_estimators": 500,
        "max_depth": 6,
        "learning_rate": 0.03,
        "num_leaves": 31,
        "min_child_samples": 30,
        "subsample": 0.8,
        "colsample_bytree": 0.7,
        "reg_alpha": 0.1,
        "reg_lambda": 1.0,
        "verbose": -1,
    })
    model.fit(X_train, y_train)

    train_probas = model.predict_proba(X_train)
    test_probas = model.predict_proba(X_test)

    # ====== Phase 4: Model Quality ======
    print("\n" + "=" * 60)
    print("Phase 4: Model Quality")
    print("=" * 60)

    print(f"Train AUC: {roc_auc_score(y_train, train_probas):.4f}")
    print(f"Test AUC:  {roc_auc_score(y_test, test_probas):.4f}")
    print(f"Train Brier: {brier_score_loss(y_train, train_probas):.4f}")
    print(f"Test Brier:  {brier_score_loss(y_test, test_probas):.4f}")

    # Probability distribution
    print("\n--- Probability Distribution (Test) ---")
    print(f"  Mean: {test_probas.mean():.4f}")
    print(f"  Std:  {test_probas.std():.4f}")
    print(f"  Min:  {test_probas.min():.4f}")
    print(f"  Max:  {test_probas.max():.4f}")
    for pct in [10, 25, 50, 75, 90]:
        print(f"  P{pct}: {np.percentile(test_probas, pct):.4f}")

    # Calibration check (raw)
    print("\n--- Calibration (Raw) ---")
    for lo, hi in [(0, 0.1), (0.1, 0.2), (0.2, 0.3), (0.3, 0.4), (0.4, 0.5), (0.5, 1.0)]:
        mask = (test_probas >= lo) & (test_probas < hi)
        if mask.sum() > 0:
            actual = y_test.values[mask].mean()
            predicted = test_probas[mask].mean()
            print(f"  [{lo:.1f}, {hi:.1f}): n={mask.sum():>5}, pred={predicted:.3f}, actual={actual:.3f}, ratio={actual/predicted:.2f}")

    # Calibrate
    calibrator = ProbabilityCalibrator(method="isotonic")
    calibrator.fit(y_train.values, train_probas)
    calibrated = calibrator.calibrate(test_probas)

    print("\n--- Calibration (After Isotonic) ---")
    for lo, hi in [(0, 0.1), (0.1, 0.2), (0.2, 0.3), (0.3, 0.4), (0.4, 0.5), (0.5, 1.0)]:
        mask = (calibrated >= lo) & (calibrated < hi)
        if mask.sum() > 0:
            actual = y_test.values[mask].mean()
            predicted = calibrated[mask].mean()
            print(f"  [{lo:.1f}, {hi:.1f}): n={mask.sum():>5}, pred={predicted:.3f}, actual={actual:.3f}, ratio={actual/predicted:.2f}")

    # ====== Phase 5: Feature Importance ======
    print("\n" + "=" * 60)
    print("Phase 5: Feature Importance")
    print("=" * 60)

    importance = model.get_feature_importance_dict(feature_cols)
    top_features = sorted(importance.items(), key=lambda x: x[1], reverse=True)
    for name, imp in top_features[:20]:
        print(f"  {name:<30} {imp:>6}")

    # ====== Phase 6: Expected Value Analysis ======
    print("\n" + "=" * 60)
    print("Phase 6: Expected Value Analysis")
    print("=" * 60)

    test_df["pred_proba"] = calibrated
    odds_col = "odds"

    if odds_col in test_df.columns:
        test_df["odds_float"] = pd.to_numeric(test_df[odds_col], errors="coerce").fillna(0)
        test_df["ev"] = test_df["pred_proba"] * test_df["odds_float"]

        print(f"\nOdds column: {odds_col}")
        print(f"Valid odds: {(test_df['odds_float'] > 0).sum()} / {len(test_df)}")

        # Single-race (複勝) analysis
        print("\n--- 単勝 EV Analysis (Top 3 = Win) ---")
        for ev_thresh in [0.8, 1.0, 1.1, 1.2, 1.3, 1.5, 2.0]:
            mask = (test_df["ev"] >= ev_thresh) & (test_df["odds_float"] > 0)
            if mask.sum() > 0:
                subset = test_df[mask]
                wins = (subset["target"] == 1).sum()
                hit_rate = wins / len(subset)
                # ROI: sum of (odds when hit) / count
                roi = subset.apply(
                    lambda r: r["odds_float"] if r["target"] == 1 else 0, axis=1
                ).sum() / len(subset)
                print(f"  EV >= {ev_thresh:.1f}: n={mask.sum():>5}, hit={hit_rate:.3f}, ROI={roi*100:.1f}%")

        # By odds range
        print("\n--- ROI by Odds Range (all bets) ---")
        for lo, hi in [(1, 3), (3, 5), (5, 10), (10, 20), (20, 50), (50, 200)]:
            mask = (test_df["odds_float"] >= lo) & (test_df["odds_float"] < hi)
            if mask.sum() > 0:
                subset = test_df[mask]
                roi = subset.apply(
                    lambda r: r["odds_float"] if r["target"] == 1 else 0, axis=1
                ).sum() / len(subset)
                hit = (subset["target"] == 1).mean()
                print(f"  [{lo:>3}-{hi:>3}): n={mask.sum():>5}, hit={hit:.3f}, ROI={roi*100:.1f}%")

        # By model confidence + odds combination
        print("\n--- Best Betting Zones (high confidence + reasonable odds) ---")
        for prob_lo in [0.3, 0.35, 0.4, 0.45, 0.5]:
            for odds_lo, odds_hi in [(2, 5), (5, 10), (10, 30)]:
                mask = (
                    (calibrated >= prob_lo) &
                    (test_df["odds_float"] >= odds_lo) &
                    (test_df["odds_float"] < odds_hi)
                )
                if mask.sum() >= 10:
                    subset = test_df[mask]
                    roi = subset.apply(
                        lambda r: r["odds_float"] if r["target"] == 1 else 0, axis=1
                    ).sum() / len(subset)
                    hit = (subset["target"] == 1).mean()
                    ev = subset["ev"].mean()
                    print(f"  prob>={prob_lo:.2f}, odds [{odds_lo}-{odds_hi}): n={mask.sum():>4}, hit={hit:.3f}, ROI={roi*100:.1f}%, avg_EV={ev:.2f}")
    else:
        print("No odds column found!")

    # ====== Phase 7: Race-level analysis ======
    print("\n" + "=" * 60)
    print("Phase 7: Race-Level Analysis")
    print("=" * 60)

    race_groups = test_df.groupby("race_id")
    race_stats = []
    for race_id, group in race_groups:
        top3_actual = set(group[group["target"] == 1]["horse_number"].values)
        top3_predicted = set(group.nlargest(3, "pred_proba")["horse_number"].values)
        overlap = len(top3_actual & top3_predicted)
        race_stats.append({
            "race_id": race_id,
            "n_horses": len(group),
            "overlap": overlap,
            "max_prob": group["pred_proba"].max(),
            "prob_spread": group["pred_proba"].max() - group["pred_proba"].min(),
        })

    race_stats_df = pd.DataFrame(race_stats)
    print(f"Total test races: {len(race_stats_df)}")
    print(f"Avg top-3 overlap: {race_stats_df['overlap'].mean():.2f} / 3")
    print(f"Perfect top-3 (3/3): {(race_stats_df['overlap'] == 3).sum()} ({(race_stats_df['overlap'] == 3).mean()*100:.1f}%)")
    print(f"At least 2/3: {(race_stats_df['overlap'] >= 2).sum()} ({(race_stats_df['overlap'] >= 2).mean()*100:.1f}%)")
    print(f"At least 1/3: {(race_stats_df['overlap'] >= 1).sum()} ({(race_stats_df['overlap'] >= 1).mean()*100:.1f}%)")

    print("\n" + "=" * 60)
    print("DIAGNOSTIC COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()
