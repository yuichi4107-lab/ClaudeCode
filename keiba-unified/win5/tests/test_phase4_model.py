"""Phase 4: 機械学習モデルのテスト

LightGBMベースの競走成績予測モデルの学習・推論・評価機能を検証する。
"""

import sys
from pathlib import Path
from datetime import date, timedelta
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# Note: These imports require LightGBM to be installed
try:
    import lightgbm as lgb
    from sklearn.metrics import roc_auc_score
    LIGHTGBM_AVAILABLE = True
except ImportError:
    LIGHTGBM_AVAILABLE = False
    print("Warning: LightGBM not available. Some tests will be skipped.")

from model.trainer import LightGBMTrainer
from model.evaluation import compute_metrics, compute_race_level_metrics


def create_sample_training_data(n_samples: int = 1000) -> pd.DataFrame:
    """
    サンプル学習データを生成

    Args:
        n_samples: サンプル数

    Returns:
        学習用DataFrame（特徴量 + ターゲット）
    """
    np.random.seed(42)

    # 特徴量: 20個の疑似特徴量を生成
    features = np.random.randn(n_samples, 20).astype(np.float32)

    # ターゲット: 特徴量の線形結合 + ノイズ（勝率約30%）
    weights = np.random.randn(20)
    logits = features @ weights
    probabilities = 1.0 / (1.0 + np.exp(-logits))
    target = (probabilities > np.percentile(probabilities, 70)).astype(int)

    # レース日付（時系列順）
    race_dates = [date(2024, 1, 1) + timedelta(days=i // 10) for i in range(n_samples)]

    # DataFrameに変換
    feature_cols = [f"feature_{i}" for i in range(20)]
    df = pd.DataFrame(features, columns=feature_cols)
    df["_race_date"] = race_dates
    df["_race_id"] = [f"202401{i//10:04d}" for i in range(n_samples)]
    df["target"] = target

    return df


def test_lightgbm_trainer_initialization():
    """
    LightGBMTrainer の初期化テスト

    テスト項目:
    - 初期化後、モデルが None であること
    - パラメータが正しく設定されていること
    """
    if not LIGHTGBM_AVAILABLE:
        print("⊘ Skipped: LightGBM not available")
        return True

    print("\n=== Testing LightGBMTrainer Initialization ===")

    trainer = LightGBMTrainer()
    assert trainer.model is None, "Model should be None initially"
    assert trainer.params is not None, "Params should be set"
    assert "objective" in trainer.params, "objective should be in params"
    assert trainer.params["objective"] == "binary", "Binary classification expected"

    print("✓ Trainer initialized correctly")
    print(f"✓ Default params: {list(trainer.params.keys())}")

    return True


def test_lightgbm_trainer_basic_training():
    """
    LightGBMTrainer の基本学習テスト

    テスト項目:
    - train() メソッドが正常に動作すること
    - モデルが学習後に non-None となること
    - 特徴量名が保存されること
    """
    if not LIGHTGBM_AVAILABLE:
        print("⊘ Skipped: LightGBM not available")
        return True

    print("\n=== Testing LightGBMTrainer Basic Training ===")

    df = create_sample_training_data(n_samples=200)
    feature_cols = [c for c in df.columns if c.startswith("feature_")]

    trainer = LightGBMTrainer()
    model = trainer.train(df, feature_cols=feature_cols, target_col="target")

    assert model is not None, "Model should be trained"
    assert trainer.model is not None, "Trainer should save model"
    assert len(trainer.feature_names) == len(feature_cols), "Feature names should be saved"

    print(f"✓ Model trained successfully")
    print(f"✓ Features: {len(trainer.feature_names)}")
    print(f"✓ n_estimators: {model.n_estimators}")

    return True


def test_lightgbm_trainer_timeseries_cv():
    """
    時系列CVテスト

    テスト項目:
    - train_with_timeseries_cv() が正常に動作すること
    - CV結果が記録されること
    - 各Fold の結果が存在すること
    """
    if not LIGHTGBM_AVAILABLE:
        print("⊘ Skipped: LightGBM not available")
        return True

    print("\n=== Testing Time-Series CV ===")

    df = create_sample_training_data(n_samples=500)
    feature_cols = [c for c in df.columns if c.startswith("feature_")]

    trainer = LightGBMTrainer()
    model = trainer.train_with_timeseries_cv(
        df,
        date_col="_race_date",
        feature_cols=feature_cols,
        target_col="target",
        n_splits=3,
    )

    assert model is not None, "Model should be trained"
    assert len(trainer.cv_results) > 0, "CV results should be recorded"

    # CV結果のメトリクス確認
    for fold_result in trainer.cv_results:
        assert "auc" in fold_result, "AUC should be in results"
        assert "logloss" in fold_result, "LogLoss should be in results"
        assert 0 <= fold_result["auc"] <= 1, "AUC should be in [0, 1]"

    avg_auc = np.mean([r["auc"] for r in trainer.cv_results])
    print(f"✓ Time-series CV completed with {len(trainer.cv_results)} folds")
    print(f"✓ Average AUC: {avg_auc:.4f}")

    return True


def test_prediction_probability_range():
    """
    予測確率が [0, 1] 範囲内であることをテスト

    テスト項目:
    - 予測確率が 0.0 から 1.0 の範囲内
    - NaN値が存在しないこと
    - inf値が存在しないこと
    """
    if not LIGHTGBM_AVAILABLE:
        print("⊘ Skipped: LightGBM not available")
        return True

    print("\n=== Testing Prediction Range ===")

    # 学習データ
    df_train = create_sample_training_data(n_samples=200)
    feature_cols = [c for c in df_train.columns if c.startswith("feature_")]

    trainer = LightGBMTrainer()
    trainer.train(df_train, feature_cols=feature_cols, target_col="target")

    # テストデータ（未使用）
    df_test = create_sample_training_data(n_samples=50)
    X_test = df_test[feature_cols].values.astype(np.float32)
    X_test = np.nan_to_num(X_test, nan=0.0, posinf=1e6, neginf=-1e6)

    # 予測
    y_pred = trainer.model.predict_proba(X_test)[:, 1]

    # 範囲チェック
    assert np.all((y_pred >= 0.0) & (y_pred <= 1.0)), "Probabilities should be in [0, 1]"
    assert not np.any(np.isnan(y_pred)), "No NaN values allowed"
    assert not np.any(np.isinf(y_pred)), "No inf values allowed"

    print(f"✓ Prediction range valid")
    print(f"✓ Min: {y_pred.min():.4f}, Max: {y_pred.max():.4f}")
    print(f"✓ Mean: {y_pred.mean():.4f}, Std: {y_pred.std():.4f}")

    return True


def test_compute_metrics():
    """
    compute_metrics() 関数のテスト

    テスト項目:
    - AUC が計算されること
    - LogLoss が計算されること
    - 精度、精密度、再現率が計算されること
    - すべてのメトリクスが有効な値であること
    """
    print("\n=== Testing Evaluation Metrics ===")

    # 予測値と実績値
    y_true = np.array([1, 0, 1, 1, 0, 0, 1, 0, 1, 0])
    y_pred_proba = np.array([0.9, 0.1, 0.8, 0.7, 0.2, 0.15, 0.95, 0.3, 0.85, 0.1])

    metrics = compute_metrics(y_true, y_pred_proba)

    assert "auc" in metrics, "AUC should be in metrics"
    assert "logloss" in metrics, "LogLoss should be in metrics"
    assert "brier" in metrics, "Brier score should be in metrics"
    assert "accuracy" in metrics, "Accuracy should be in metrics"

    # 値の範囲確認
    assert 0 <= metrics["auc"] <= 1, "AUC should be in [0, 1]"
    assert metrics["logloss"] >= 0, "LogLoss should be >= 0"
    assert 0 <= metrics["brier"] <= 1, "Brier should be in [0, 1]"
    assert 0 <= metrics["accuracy"] <= 1, "Accuracy should be in [0, 1]"

    print(f"✓ Metrics computed successfully")
    print(f"  AUC: {metrics['auc']:.4f}")
    print(f"  LogLoss: {metrics['logloss']:.4f}")
    print(f"  Brier: {metrics['brier']:.4f}")
    print(f"  Accuracy: {metrics['accuracy']:.4f}")

    return True


def test_compute_race_level_metrics():
    """
    レース単位の評価指標テスト

    テスト項目:
    - Top1 的中率が計算されること
    - Top3 的中率が計算されること
    - 平均1着馬順位が計算されること
    """
    print("\n=== Testing Race-Level Metrics ===")

    # サンプルレース予測結果
    df = pd.DataFrame({
        "_race_id": ["R1"] * 10 + ["R2"] * 10,
        "_finish_position": [1, 0, 0, 0, 0, 0, 0, 0, 0, 0] + [0, 0, 1, 0, 0, 0, 0, 0, 0, 0],
        "calibrated_prob": [0.05, 0.12, 0.11, 0.10, 0.09, 0.08, 0.07, 0.06, 0.05, 0.02] +
                          [0.12, 0.11, 0.10, 0.09, 0.08, 0.07, 0.06, 0.05, 0.04, 0.03],
    })

    metrics = compute_race_level_metrics(df)

    assert "top1_hit_rate" in metrics, "top1_hit_rate should exist"
    assert "top3_hit_rate" in metrics, "top3_hit_rate should exist"
    assert "avg_winner_rank" in metrics, "avg_winner_rank should exist"
    assert 0 <= metrics["top1_hit_rate"] <= 1, "top1_hit_rate should be in [0, 1]"
    assert 0 <= metrics["top3_hit_rate"] <= 1, "top3_hit_rate should be in [0, 1]"

    print(f"✓ Race-level metrics computed successfully")
    print(f"  Top1 Hit Rate: {metrics['top1_hit_rate']:.2%}")
    print(f"  Top3 Hit Rate: {metrics['top3_hit_rate']:.2%}")
    print(f"  Avg Winner Rank: {metrics['avg_winner_rank']:.2f}")

    return True


def test_nan_inf_handling():
    """
    NaN/Inf 値のハンドリングテスト

    テスト項目:
    - NaN値が含まれるデータでも学習できること
    - Inf値が含まれるデータでも学習できること
    - 予測結果にNaN/Infが含まれないこと
    """
    if not LIGHTGBM_AVAILABLE:
        print("⊘ Skipped: LightGBM not available")
        return True

    print("\n=== Testing NaN/Inf Handling ===")

    df = create_sample_training_data(n_samples=200)
    feature_cols = [c for c in df.columns if c.startswith("feature_")]

    # NaN/Inf を注入
    df_dirty = df.copy()
    df_dirty.loc[0:5, feature_cols[0]] = np.nan
    df_dirty.loc[10:15, feature_cols[1]] = np.inf
    df_dirty.loc[20:25, feature_cols[2]] = -np.inf

    trainer = LightGBMTrainer()
    model = trainer.train(df_dirty, feature_cols=feature_cols, target_col="target")

    # 予測
    X_test = df_dirty[feature_cols].head(50).values.astype(np.float32)
    X_test = np.nan_to_num(X_test, nan=0.0, posinf=1e6, neginf=-1e6)
    y_pred = trainer.model.predict_proba(X_test)[:, 1]

    assert not np.any(np.isnan(y_pred)), "Predictions should not contain NaN"
    assert not np.any(np.isinf(y_pred)), "Predictions should not contain Inf"

    print(f"✓ NaN/Inf handling successful")
    print(f"✓ Predictions clean and valid")

    return True


def run_all_phase4_tests():
    """
    Phase 4 の全テストを実行
    """
    print("\n" + "=" * 70)
    print("Phase 4: Machine Learning Model - Test Suite")
    print("=" * 70)

    if not LIGHTGBM_AVAILABLE:
        print("\n⚠ Warning: LightGBM is not installed.")
        print("Install with: pip install lightgbm scikit-learn")
        return False

    tests = [
        ("LightGBMTrainer Initialization", test_lightgbm_trainer_initialization),
        ("LightGBMTrainer Basic Training", test_lightgbm_trainer_basic_training),
        ("Time-Series Cross-Validation", test_lightgbm_trainer_timeseries_cv),
        ("Prediction Range Validation", test_prediction_probability_range),
        ("Evaluation Metrics", test_compute_metrics),
        ("Race-Level Metrics", test_compute_race_level_metrics),
        ("NaN/Inf Handling", test_nan_inf_handling),
    ]

    results = []
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, True, None))
            print(f"✓ {test_name} PASSED")
        except AssertionError as e:
            results.append((test_name, False, str(e)))
            print(f"✗ {test_name} FAILED: {e}")
        except Exception as e:
            results.append((test_name, False, str(e)))
            print(f"✗ {test_name} ERROR: {e}")
            import traceback
            traceback.print_exc()

    print("\n" + "=" * 70)
    print("Test Summary")
    print("=" * 70)

    for test_name, result, error in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status}: {test_name}")
        if error:
            print(f"       {error[:80]}")

    passed = sum(1 for _, r, _ in results if r)
    total = len(results)
    print(f"\nTotal: {passed}/{total} tests passed")

    return all(r for _, r, _ in results)


if __name__ == "__main__":
    success = run_all_phase4_tests()
    sys.exit(0 if success else 1)
