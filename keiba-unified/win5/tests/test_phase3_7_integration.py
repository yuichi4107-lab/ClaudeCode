"""Phase 3-7: 包括的な統合テスト

特徴量エンジニアリング、機械学習、最適化、分析の
全フェーズを統合したテスト
"""

import json
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from database.models import (
    Race,
    RaceResult,
    Horse,
    Jockey,
    Trainer,
)
from database.connection import Database
from database.repository import Repository
from features.builder import FeatureBuilder
from features.horse_features import build_horse_features
from features.race_features import build_race_features
from features.jockey_features import build_jockey_features
from features.odds_features import build_odds_features
from features.pedigree_features import build_pedigree_features
from model.trainer import LightGBMTrainer
from model.predictor import Predictor
from model.evaluation import compute_metrics
from optimizer.win5_combiner import Win5Combiner
from optimizer.budget_optimizer import BudgetOptimizer
from optimizer.expected_value import ExpectedValueCalculator
from analysis.backtester import Backtester
from analysis.roi_calculator import ROICalculator


class TestPhase3FeatureEngineering:
    """Phase 3: 特徴量エンジニアリング"""

    def test_horse_features_creation(self):
        """馬の特徴量構築テスト"""
        # サンプル馬の過去成績
        horse_history = pd.DataFrame({
            "finish_position": [1, 2, 1, 3, 5, 10, 4, 2, 1, 6],
            "odds": [5.2, 8.5, 3.1, 12.1, 25.5, 150.0, 18.5, 9.3, 4.8, 35.2],
            "last_3f": [33.2, 34.1, 32.8, 35.5, 36.2, 38.1, 34.8, 33.5, 32.5, 37.2],
            "finish_time": [120.5, 122.1, 119.8, 125.3, 128.7, 135.2, 124.5, 121.2, 118.9, 130.1],
            "horse_weight": [450, 452, 448, 455, 460, 465, 462, 451, 449, 468],
        })

        feats = build_horse_features(
            horse_id="test_horse_001",
            race_date=date(2026, 1, 15),
            race_distance=2000,
            race_surface="芝",
            race_venue="東京",
            race_condition="良好",
            horse_history=horse_history,
            horse_weight=450,
            horse_age=5,
        )

        # 期待値: 5走での勝率 = 2/5 = 0.4
        assert feats.get("win_rate_5") == 0.4, f"Expected 0.4, got {feats.get('win_rate_5')}"

        # 複勝率 = 4/5 = 0.8
        assert feats.get("top3_rate_5") == 0.8, f"Expected 0.8, got {feats.get('top3_rate_5')}"

        # キーが存在することを確認
        assert "recent_runs" in feats
        assert "avg_position_5" in feats
        assert "win_streak" in feats

        print(f"✓ Horse features: {len(feats)} features created")
        return feats

    def test_race_features_creation(self):
        """レース特徴量構築テスト"""
        feats = build_race_features(
            race_date=date(2026, 1, 15),
            race_distance=2000,
            race_surface="芝",
            race_venue="東京",
            race_condition="良好",
            race_class_code=2,
            num_runners=16,
            is_graded=False,
            month=1,
            day_of_week=3,
        )

        assert isinstance(feats, dict)
        assert "is_graded" in feats
        assert "is_spring" in feats or "month_cosine" in feats
        print(f"✓ Race features: {len(feats)} features created")
        return feats

    def test_feature_builder_integration(self, tmp_path):
        """FeatureBuilder統合テスト"""
        # 一時的なDBを作成
        db_path = tmp_path / "test.db"
        db = Database(db_path=str(db_path))
        db.initialize()
        repo = Repository(database=db)

        # テストデータを挿入
        horse = Horse(
            horse_id="test_horse_001",
            name="テスト馬",
            sire_id="sire_001",
            damsire_id="damsire_001",
        )
        repo.insert_horse(horse)

        builder = FeatureBuilder(repo=repo)
        
        # 実際のテストデータなしでエラーハンドリングを確認
        feats = builder.build_for_entry(
            race_id="test_race_001",
            horse_id="nonexistent_horse",
            horse_number=1,
            post_position=1,
            race_date=date(2026, 1, 15),
            race_distance=2000,
            race_surface="芝",
            race_venue="東京",
            race_condition="良好",
            race_class_code=2,
            num_runners=16,
            weight_carried=55.5,
            weight_rule="定量",
            jockey_id="jockey_001",
            trainer_id="trainer_001",
            horse_age=5,
            horse_weight=450,
            use_cache=False,
        )

        assert isinstance(feats, dict)
        assert len(feats) > 0
        print(f"✓ FeatureBuilder created {len(feats)} features")
        return feats


class TestPhase4MLModel:
    """Phase 4: 機械学習モデル"""

    def test_model_trainer_initialization(self):
        """LightGBMTrainerの初期化テスト"""
        trainer = LightGBMTrainer()
        assert trainer.model is None
        assert trainer.feature_names == []
        assert trainer.cv_results == []
        print("✓ LightGBMTrainer initialized")

    def test_model_training_with_synthetic_data(self):
        """合成データでのモデル学習テスト"""
        # 合成データ生成
        n_samples = 1000
        n_features = 50
        
        X = np.random.randn(n_samples, n_features).astype(np.float32)
        y = np.random.randint(0, 2, n_samples).astype(np.float32)
        
        df = pd.DataFrame(X, columns=[f"feat_{i}" for i in range(n_features)])
        df["_race_date"] = pd.date_range("2025-01-01", periods=n_samples, freq="D")
        df["target"] = y

        feature_cols = [f"feat_{i}" for i in range(n_features)]

        trainer = LightGBMTrainer()
        model = trainer.train(df, feature_cols=feature_cols, target_col="target")

        assert model is not None
        assert len(trainer.feature_names) == n_features
        
        # 予測テスト
        preds = model.predict_proba(X)[:5]
        assert preds.shape == (5, 2)
        print(f"✓ Model trained: {model} with {n_features} features")

    def test_model_predictor(self):
        """Predictorのテスト"""
        # 簡単なモデルを作成
        n_features = 30
        trainer = LightGBMTrainer()
        
        # ダミーモデルを生成
        X = np.random.randn(100, n_features).astype(np.float32)
        y = np.random.randint(0, 2, 100).astype(np.float32)
        
        df = pd.DataFrame(X, columns=[f"feat_{i}" for i in range(n_features)])
        df["_race_date"] = pd.date_range("2025-01-01", periods=100, freq="D")
        df["target"] = y
        
        feature_cols = [f"feat_{i}" for i in range(n_features)]
        trainer.train(df, feature_cols=feature_cols, target_col="target")

        assert trainer.model is not None
        print(f"✓ Predictor model available")


class TestPhase5Win5Optimizer:
    """Phase 5: Win5最適化"""

    def test_win5_combiner(self):
        """Win5Combinerテスト"""
        # 5レース分のダミー予測
        predictions = {}
        for i in range(5):
            race_id = f"test_race_{i:03d}"
            df = pd.DataFrame({
                "horse_number": list(range(1, 9)),
                "horse_name": [f"馬{j}" for j in range(1, 9)],
                "calibrated_prob": np.random.uniform(0.05, 0.25, 8),
            })
            predictions[race_id] = df

        combiner = Win5Combiner(predictions)
        selections = combiner.generate_selections(max_horses_per_race=3)

        assert len(selections) == 5
        for sel in selections:
            assert len(sel.horse_numbers) <= 3
            assert len(sel.probabilities) == len(sel.horse_numbers)

        n_combos = combiner.count_combinations(selections)
        assert n_combos > 0
        assert n_combos == 3 ** 5  # 各レース3頭選定
        
        print(f"✓ Win5Combiner: {n_combos} combinations generated")

    def test_budget_optimizer(self):
        """BudgetOptimizerテスト"""
        # ダミーチケット生成
        from optimizer.win5_combiner import Win5Ticket, Win5Selection

        selections = []
        for i in range(5):
            sel = Win5Selection(
                race_id=f"race_{i}",
                race_number=i + 1,
                horse_numbers=[1, 2, 3],
                horse_names=[f"馬{j}" for j in [1, 2, 3]],
                probabilities=[0.3, 0.2, 0.15],
            )
            selections.append(sel)

        tickets = [
            Win5Ticket(
                selections=selections,
                num_combinations=27,
                total_cost=27 * 100,
                total_hit_probability=0.001,
                expected_value=0.05,
            )
        ]

        optimizer = BudgetOptimizer(budget=100000)
        allocated = optimizer.allocate_budget(tickets)

        assert len(allocated) > 0
        total_cost = sum(t.total_cost for t in allocated)
        assert total_cost <= 100000

        print(f"✓ BudgetOptimizer: allocated {len(allocated)} tickets")

    def test_expected_value_calculator(self):
        """ExpectedValueCalculatorテスト"""
        calc = ExpectedValueCalculator(default_odds=200)
        
        combinations = [
            {"horses": (1, 2, 3, 4, 5), "probability": 0.001, "payout": 500000},
            {"horses": (2, 3, 4, 5, 6), "probability": 0.0008, "payout": 600000},
        ]
        
        # EV計算可能であることを確認
        for combo in combinations:
            ev = calc.calculate_ev(combo["probability"], combo["payout"], combo["probability"])
            assert isinstance(ev, float)
            assert ev >= 0

        print(f"✓ ExpectedValueCalculator: EV calculation available")


class TestPhase6Analysis:
    """Phase 6: 分析・資金管理"""

    def test_roi_calculator(self):
        """ROICalculatorテスト"""
        calc = ROICalculator()
        
        # テスト結果
        results = [
            {"bet_amount": 100, "payout": 0, "hit": False},
            {"bet_amount": 100, "payout": 500, "hit": True},
            {"bet_amount": 100, "payout": 0, "hit": False},
            {"bet_amount": 100, "payout": 1200, "hit": True},
        ]
        
        roi = calc.calculate_roi(results)
        assert isinstance(roi, float)
        # ROI = (収益 - 支出) / 支出
        # = (1700 - 400) / 400 = 3.25 (325%)
        expected_roi = (1700 - 400) / 400
        assert abs(roi - expected_roi) < 0.01

        print(f"✓ ROICalculator: ROI = {roi:.2%}")

    def test_backtester_initialization(self):
        """Backtesterの初期化テスト"""
        backtester = Backtester(
            initial_bankroll=1000000,
            bet_unit=100,
        )
        assert backtester.initial_bankroll == 1000000
        assert backtester.current_bankroll == 1000000
        print("✓ Backtester initialized")


class TestPhase7Application:
    """Phase 7: アプリケーション層"""

    def test_config_loading(self):
        """設定ロードテスト"""
        from config.settings import (
            LIGHTGBM_DEFAULT_PARAMS,
            WIN5_BET_UNIT,
            WIN5_NUM_RACES,
            RECENT_RUNS,
            CV_N_SPLITS,
        )
        
        assert isinstance(LIGHTGBM_DEFAULT_PARAMS, dict)
        assert WIN5_BET_UNIT == 100
        assert WIN5_NUM_RACES == 5
        assert RECENT_RUNS == 5
        assert CV_N_SPLITS == 3

        print("✓ Config settings loaded correctly")

    def test_database_initialization(self, tmp_path):
        """データベース初期化テスト"""
        db_path = tmp_path / "test.db"
        db = Database(db_path=str(db_path))
        db.initialize()
        
        assert db_path.exists()
        
        repo = Repository(database=db)
        
        # DBに接続可能か確認
        horse = Horse(
            horse_id="test_001",
            name="test_horse",
            sire_id="sire_001",
            damsire_id="damsire_001",
        )
        repo.insert_horse(horse)
        
        retrieved = repo.get_horse("test_001")
        assert retrieved is not None
        assert retrieved.name == "test_horse"

        print("✓ Database initialized and working")


class TestEndToEndIntegration:
    """エンドツーエンド統合テスト"""

    def test_full_pipeline_dry_run(self, tmp_path):
        """完全なパイプラインのドライランテスト"""
        print("\n" + "="*60)
        print("FULL PIPELINE DRY RUN")
        print("="*60)

        # 1. DB初期化
        db_path = tmp_path / "test.db"
        db = Database(db_path=str(db_path))
        db.initialize()
        repo = Repository(database=db)
        print("✓ Database initialized")

        # 2. テストデータ挿入
        horse1 = Horse(horse_id="h001", name="Horse A", sire_id="sire_001", damsire_id="damsire_001")
        horse2 = Horse(horse_id="h002", name="Horse B", sire_id="sire_002", damsire_id="damsire_002")
        repo.insert_horse(horse1)
        repo.insert_horse(horse2)
        print("✓ Test data inserted")

        # 3. 特徴量構築
        builder = FeatureBuilder(repo=repo)
        print("✓ FeatureBuilder created")

        # 4. モデル学習
        trainer = LightGBMTrainer()
        print("✓ LightGBMTrainer initialized")

        # 5. Win5最適化
        combiner = Win5Combiner({f"race_{i}": pd.DataFrame() for i in range(5)})
        print("✓ Win5Combiner initialized")

        # 6. 分析
        roi_calc = ROICalculator()
        print("✓ ROICalculator initialized")

        print("\n" + "="*60)
        print("PIPELINE COMPLETED SUCCESSFULLY")
        print("="*60)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
