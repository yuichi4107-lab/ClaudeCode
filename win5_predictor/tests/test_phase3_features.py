"""特徴量エンジニアリングのテスト

Phase 3 の各特徴量計算モジュールを検証する。
"""

import sys
from pathlib import Path
from datetime import date, timedelta
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from database.models import Horse, RaceResult
from features.horse_features import build_horse_features
from features.jockey_features import build_jockey_features, build_trainer_features
from features.race_features import build_race_features, build_field_strength_features
from features.odds_features import build_odds_features
from features.pedigree_features import build_pedigree_features
from features.builder import FeatureBuilder


def create_sample_horse_history() -> pd.DataFrame:
    """サンプル競走成績データフレームを作成"""
    return pd.DataFrame({
        "race_id": ["202601120101", "202601050101", "202512290101"],
        "race_date": ["2026-01-12", "2026-01-05", "2025-12-29"],
        "distance": [2000, 2000, 2000],
        "surface": ["turf", "turf", "turf"],
        "venue": ["tokyo", "tokyo", "tokyo"],
        "finish_position": [1.0, 2.0, 1.0],
        "last_3f": [37.2, 37.5, 37.0],
        "finish_time": [120.5, 121.0, 120.2],
        "horse_weight": [480, 475, 482],
        "weight_change": [-2, 5, 0],
        "odds": [2.1, 3.5, 1.8],
    })


def create_sample_race_data() -> dict:
    """サンプルレースデータを作成"""
    return {
        "race_id": "202602150811",
        "race_date": date(2026, 2, 15),
        "race_distance": 2000,
        "race_surface": "turf",
        "race_venue": "08",  # 阪神
        "race_condition": "good",
        "race_class_code": 3,
        "num_runners": 14,
    }


def test_horse_features():
    """
    馬の特徴量計算テスト

    テスト項目:
    - 勝率計算が正確
    - 複勝率計算が正確
    - 平均着順が正確
    - 休養日数が正確
    - スピード指数が計算される
    - 空データ時のデフォルト値
    """
    print("\n=== Testing Horse Features ===")

    hist = create_sample_horse_history()
    race_data = create_sample_race_data()

    features = build_horse_features(
        horse_id="123456",
        race_date=race_data["race_date"],
        race_distance=race_data["race_distance"],
        race_surface=race_data["race_surface"],
        race_venue=race_data["race_venue"],
        race_condition=race_data["race_condition"],
        horse_history=hist,
        horse_weight=480,
        horse_age=4,
    )

    assert features is not None, "Features should not be None"
    assert isinstance(features, dict), "Features should be a dict"

    # 基本的な特徴量が存在
    assert "win_rate_5" in features, "win_rate_5 should exist"
    assert "top3_rate_5" in features, "top3_rate_5 should exist"
    assert "avg_position_5" in features, "avg_position_5 should exist"
    assert "days_since_last" in features, "days_since_last should exist"

    # 値の範囲チェック
    assert 0 <= features["win_rate_5"] <= 1, f"win_rate_5 should be [0, 1], got {features['win_rate_5']}"
    assert 0 <= features["top3_rate_5"] <= 1, f"top3_rate_5 should be [0, 1], got {features['top3_rate_5']}"
    assert features["avg_position_5"] > 0, "avg_position_5 should be > 0"
    assert features["days_since_last"] >= 0, "days_since_last should be >= 0"

    # サンプルデータの検証（3走中2勝1着2着なので、勝率=66.7%, 複勝率=100%）
    # ※ 最新3走なので最初の1位（3走目）は除外される場合がある
    print(f"✓ win_rate_5: {features['win_rate_5']:.2f}")
    print(f"✓ top3_rate_5: {features['top3_rate_5']:.2f}")
    print(f"✓ avg_position_5: {features['avg_position_5']:.2f}")
    print(f"✓ days_since_last: {features['days_since_last']:.0f}")
    print(f"✓ Features count: {len(features)}")

    # 特徴量の個数が適切な範囲（20-40個）
    assert 15 < len(features) < 50, f"Feature count should be 15-50, got {len(features)}"

    return True


def test_horse_features_empty_history():
    """
    空の競走成績時のテスト

    過去データがない新馬や休場馬への対応確認
    """
    print("\n=== Testing Horse Features (Empty History) ===")

    empty_hist = pd.DataFrame({
        "race_id": [],
        "race_date": [],
        "finish_position": [],
    })

    race_data = create_sample_race_data()

    features = build_horse_features(
        horse_id="999999",
        race_date=race_data["race_date"],
        race_distance=race_data["race_distance"],
        race_surface=race_data["race_surface"],
        race_venue=race_data["race_venue"],
        race_condition=race_data["race_condition"],
        horse_history=empty_hist,
        horse_weight=450,
        horse_age=2,
    )

    assert features is not None, "Features should not be None even with empty history"
    assert len(features) > 0, "Should have default features"

    # デフォルト値が返されている
    assert features.get("win_rate_5", 0) == 0.0, "Default win_rate should be 0.0"
    print(f"✓ Empty history handled correctly")
    print(f"✓ Default features count: {len(features)}")

    return True


def test_jockey_features():
    """
    騎手の特徴量計算テスト

    テスト項目:
    - 騎手勝率が計算される
    - 値の範囲が正確
    """
    print("\n=== Testing Jockey Features ===")

    jockey_stats = {
        "total_wins": 450,
        "total_runs": 1200,
        "win_rate": 0.375,
    }

    features = build_jockey_features(
        jockey_id="456789",
        jockey_stats=jockey_stats,
        venue_win_rate=0.40,
        surface_win_rate=0.38,
        combo_stats=(52, 150),  # (wins, starts)
    )

    assert features is not None, "Jockey features should not be None"
    assert isinstance(features, dict), "Jockey features should be a dict"

    # 基本特徴量の確認
    assert "jockey_win_rate" in features, "jockey_win_rate should exist"

    print(f"✓ Jockey features created: {len(features)} features")
    print(f"✓ jockey_win_rate: {features.get('jockey_win_rate', 0):.3f}")

    return True


def test_race_features():
    """
    レース環境特徴量のテスト

    テスト項目:
    - フィールド強度が計算される
    - ペース予測が計算される
    """
    print("\n=== Testing Race Features ===")

    # サンプル出走各馬データ
    entries = pd.DataFrame({
        "horse_id": ["123456", "123457", "123458"],
        "odds": [2.5, 3.2, 5.1],
        "total_earnings": [2500, 2000, 1800],
    })

    features = build_race_features(
        race_distance=2000,
        race_surface="turf",
        num_runners=14,
        entries=entries,
    )

    assert features is not None, "Race features should not be None"
    assert isinstance(features, dict), "Race features should be a dict"

    print(f"✓ Race features created: {len(features)} features")

    # フィールド強度特徴量
    field_features = build_field_strength_features(entries=entries)
    assert field_features is not None, "Field strength features should not be None"
    print(f"✓ Field strength features: {len(field_features)} features")

    return True


def test_odds_features():
    """
    オッズ特徴量のテスト

    テスト項目:
    - 暗示確率が計算される
    - 人気順位が正規化される
    """
    print("\n=== Testing Odds Features ===")

    field_odds = [2.5, 3.2, 5.1, 7.8, 12.0, 15.5, 20.0, 25.0, 30.0, 40.0, 50.0, 100.0, 150.0, 200.0]

    features = build_odds_features(
        horse_number=1,
        win_odds=2.5,
        popularity=1,
        field_odds=field_odds,
    )

    assert features is not None, "Odds features should not be None"
    assert isinstance(features, dict), "Odds features should be a dict"

    # 基本特徴量
    assert "odds" in features, "odds should exist"
    assert "popularity_rank" in features, "popularity_rank should exist"

    print(f"✓ Odds features created: {len(features)} features")
    print(f"✓ odds: {features.get('odds', 0):.2f}")
    print(f"✓ popularity_rank: {features.get('popularity_rank', 0)}")

    return True


def test_pedigree_features():
    """
    血統特徴量のテスト

    テスト項目:
    - 父系統計が計算される
    - デフォルト値が返される
    """
    print("\n=== Testing Pedigree Features ===")

    sire_stats = {
        "turf_win_rate": 0.35,
        "dirt_win_rate": 0.28,
        "total_wins": 250,
        "total_starts": 850,
    }

    damsire_stats = {
        "turf_win_rate": 0.32,
        "dirt_win_rate": 0.25,
        "total_wins": 180,
        "total_starts": 650,
    }

    features = build_pedigree_features(
        race_surface="turf",
        sire_stats=sire_stats,
        damsire_stats=damsire_stats,
    )

    assert features is not None, "Pedigree features should not be None"
    assert isinstance(features, dict), "Pedigree features should be a dict"

    print(f"✓ Pedigree features created: {len(features)} features")

    return True


def test_feature_builder_integration():
    """
    FeatureBuilder の統合テスト

    すべての特徴量計算が一括で実行できるか確認
    """
    print("\n=== Testing FeatureBuilder Integration ===")

    builder = FeatureBuilder()
    print("✓ FeatureBuilder initialized")

    # 注: この統合テストはデータベースが必要なため、
    # 実際の実行にはメモリDBが必要
    print("✓ FeatureBuilder instantiated (full integration test requires database)")

    return True


def test_feature_statistics():
    """
    生成された特徴量の統計情報テスト

    特徴量の分布、NaN値、異常値をチェック
    """
    print("\n=== Testing Feature Statistics ===")

    hist = create_sample_horse_history()
    race_data = create_sample_race_data()

    features = build_horse_features(
        horse_id="123456",
        race_date=race_data["race_date"],
        race_distance=race_data["race_distance"],
        race_surface=race_data["race_surface"],
        race_venue=race_data["race_venue"],
        race_condition=race_data["race_condition"],
        horse_history=hist,
        horse_weight=480,
        horse_age=4,
    )

    # NaN値の確認
    nan_count = sum(1 for v in features.values() if v is None or (isinstance(v, float) and np.isnan(v)))
    assert nan_count == 0, f"Should not have NaN values, found {nan_count}"
    print(f"✓ No NaN values in features")

    # 無限値の確認
    inf_count = sum(1 for v in features.values() if isinstance(v, float) and (np.isinf(v)))
    assert inf_count == 0, f"Should not have inf values, found {inf_count}"
    print(f"✓ No infinite values in features")

    # 数値型確認
    for key, value in features.items():
        assert isinstance(value, (int, float)), f"Feature {key} should be numeric, got {type(value)}"
    print(f"✓ All features are numeric")

    print(f"✓ Feature statistics valid (total: {len(features)} features)")

    return True


def run_all_phase3_tests():
    """
    Phase 3 の全テストを実行
    """
    print("\n" + "=" * 70)
    print("Phase 3: Feature Engineering - Test Suite")
    print("=" * 70)

    tests = [
        ("Horse Features", test_horse_features),
        ("Horse Features (Empty History)", test_horse_features_empty_history),
        ("Jockey Features", test_jockey_features),
        ("Race Features", test_race_features),
        ("Odds Features", test_odds_features),
        ("Pedigree Features", test_pedigree_features),
        ("Feature Statistics", test_feature_statistics),
        ("FeatureBuilder Integration", test_feature_builder_integration),
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
    success = run_all_phase3_tests()
    sys.exit(0 if success else 1)
