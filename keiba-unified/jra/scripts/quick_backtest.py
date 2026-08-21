"""試行バックテスト（高速版）

高速パイプラインで特徴量生成→モデル訓練→バックテスト→レポート生成を実行する。
Train: ~2024-06, Test: 2024-07~
"""

import os
import sys
import time
import sqlite3

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import numpy as np
import pandas as pd

from src.features.fast_pipeline import FastFeaturePipeline
from src.models.lgbm_model import LGBMModel
from src.backtest.engine import BacktestEngine, BacktestResult
from src.backtest.metrics import MetricsCalculator
from src.strategies.value_betting import ValueBettingStrategy
from src.strategies.multi_combo import MultiComboStrategy
from src.strategies.hybrid_portfolio import HybridPortfolioStrategy
from src.strategies.upset_hunter import UpsetHunterStrategy
from src.reporting.html_report import HTMLReportGenerator
from src.utils.config_loader import get_db_path, load_strategies_config
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


def run_backtest_for_strategy(strategy, features_df, results_df, payoffs_df,
                              feature_cols, train_mask, test_mask):
    """1戦略のバックテストを実行"""
    train_df = features_df[train_mask]
    test_df = features_df[test_mask].copy()

    X_train = train_df[feature_cols].fillna(0)
    y_train = train_df["target"]

    # モデル訓練（正則化強化）
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

    # 予測（キャリブレーション不要 - 生モデルの方がキャリブレーション良好）
    X_test = test_df[feature_cols].fillna(0)
    probas = model.predict_proba(X_test)
    test_df["pred_proba"] = probas

    # ベット生成（レースごと）
    result = BacktestResult()
    bankroll = 1_000_000
    daily_pnl = {}

    race_ids = test_df["race_id"].unique()
    for race_id in race_ids:
        race_mask = test_df["race_id"] == race_id
        race_df = test_df[race_mask]
        race_probas = race_df["pred_proba"].values
        race_date = str(race_df["race_date"].iloc[0])

        bets = strategy.generate_bets(race_df, race_probas, bankroll)
        if not bets:
            continue

        engine = BacktestEngine()
        for bet in bets:
            bet.race_id = race_id
            bet.race_date = race_date
            bet.is_hit = engine._check_hit(bet, results_df)
            if bet.is_hit:
                bet.payout = engine._calculate_payout(bet, payoffs_df)
            else:
                bet.payout = 0.0
            bet.profit = bet.payout - bet.amount

            result.bets.append(bet)
            result.total_investment += bet.amount
            result.total_payout += bet.payout
            bankroll += bet.profit

            if race_date not in daily_pnl:
                daily_pnl[race_date] = 0.0
            daily_pnl[race_date] += bet.profit

    # Equity curve / daily returns
    if daily_pnl:
        sorted_dates = sorted(daily_pnl.keys())
        equity = 1_000_000
        eq_vals, ret_vals = {}, {}
        for d in sorted_dates:
            equity += daily_pnl[d]
            eq_vals[d] = equity
            ret_vals[d] = daily_pnl[d]
        result.equity_curve = pd.Series(eq_vals)
        result.equity_curve.index = pd.to_datetime(result.equity_curve.index)
        result.daily_returns = pd.Series(ret_vals)
        result.daily_returns.index = pd.to_datetime(result.daily_returns.index)

    return result, model


def main():
    db_path = get_db_path()

    # ====== Phase 1: 高速特徴量生成 ======
    print("=" * 60)
    print("Phase 1: Building features (fast pipeline)...")
    print("=" * 60)

    t0 = time.time()
    pipeline = FastFeaturePipeline(db_path)
    features_df = pipeline.build_features("2021-01-01", "2025-12-31")
    elapsed = time.time() - t0

    if features_df.empty:
        print("ERROR: No features generated")
        return

    # target: 3着以内 = 1
    if "finish_order" in features_df.columns:
        features_df["target"] = (features_df["finish_order"] <= 3).astype(int)
    else:
        features_df["target"] = 0

    print(f"Total feature matrix: {features_df.shape} in {elapsed:.1f}s")

    # ====== Phase 2: Train/Test分割 ======
    print("\n" + "=" * 60)
    print("Phase 2: Train/Test Split")
    print("=" * 60)

    dates = pd.to_datetime(features_df["race_date"])
    train_mask = dates <= "2024-06-30"
    test_mask = dates > "2024-06-30"

    n_train = train_mask.sum()
    n_test = test_mask.sum()
    print(f"Train: {n_train} rows, Test: {n_test} rows")

    if n_train < 100 or n_test < 50:
        # フォールバック: 80/20分割
        print("Insufficient test data, using 80/20 split")
        dates_sorted = dates.sort_values()
        cutoff_date = dates_sorted.iloc[int(len(dates_sorted) * 0.8)]
        train_mask = dates <= cutoff_date
        test_mask = dates > cutoff_date
        n_train = train_mask.sum()
        n_test = test_mask.sum()
        print(f"Train: {n_train} rows, Test: {n_test} rows")

    meta_cols = {"race_id", "race_date", "horse_number", "horse_id",
                 "horse_name", "finish_order", "target", "pred_proba"}
    feature_cols = [c for c in features_df.columns if c not in meta_cols]
    print(f"Features: {len(feature_cols)}")

    # 結果テーブル・払戻テーブル読み込み
    print("\nLoading results and payoffs from DB...")
    conn = sqlite3.connect(db_path, timeout=10)
    results_df = pd.read_sql(
        "SELECT race_id, horse_number, finish_order as finish_position FROM race_results",
        conn
    )
    payoffs_df = pd.read_sql(
        "SELECT race_id, bet_type, combination, payout as payout_amount FROM payoffs",
        conn
    )
    conn.close()
    print(f"Results: {len(results_df)} rows, Payoffs: {len(payoffs_df)} rows")

    # ====== Phase 3: 4戦略バックテスト ======
    print("\n" + "=" * 60)
    print("Phase 3: Running backtests...")
    print("=" * 60)

    strategy_config = load_strategies_config()

    strategies = {
        "Value Betting": ValueBettingStrategy(strategy_config),
        "Multi Combo": MultiComboStrategy(strategy_config),
        "Hybrid Portfolio": HybridPortfolioStrategy(strategy_config),
        "Upset Hunter": UpsetHunterStrategy(strategy_config),
    }

    all_results = {}
    all_metrics = {}
    test_races = features_df[test_mask]["race_id"].nunique()
    test_days = pd.to_datetime(features_df[test_mask]["race_date"]).dt.date.nunique()

    for name, strategy in strategies.items():
        print(f"\n--- {name} ---")
        t0 = time.time()
        result, model = run_backtest_for_strategy(
            strategy, features_df, results_df, payoffs_df,
            feature_cols, train_mask, test_mask
        )
        elapsed = time.time() - t0

        metrics = MetricsCalculator.calculate_all(result, test_races, test_days)
        all_results[name] = result
        all_metrics[name] = metrics

        print(f"  Bets: {metrics['total_bets']}")
        print(f"  Investment: {metrics['total_investment']:,.0f} JPY")
        print(f"  Payout: {metrics['total_payout']:,.0f} JPY")
        print(f"  Net Profit: {metrics['net_profit']:+,.0f} JPY")
        print(f"  ROI: {metrics['roi_pct']:.1f}%")
        print(f"  Hit Rate: {metrics['hit_rate_pct']:.1f}%")
        print(f"  Purchase Rate: {metrics['purchase_rate_pct']:.1f}%")
        print(f"  Daily Win Rate: {metrics['daily_win_rate_pct']:.1f}%")
        print(f"  Max Drawdown: {metrics['max_drawdown_pct']:.1f}%")
        print(f"  Sharpe: {metrics['sharpe_ratio']:.2f}")
        print(f"  Profit Factor: {metrics['profit_factor']:.2f}")
        print(f"  Time: {elapsed:.1f}s")

    # ====== Phase 4: レポート生成 ======
    print("\n" + "=" * 60)
    print("Phase 4: Generating reports...")
    print("=" * 60)

    gen = HTMLReportGenerator()

    # 個別レポート
    for name, result in all_results.items():
        safe_name = name.replace(" ", "_").lower()
        path = f"data/reports/backtest_{safe_name}.html"
        gen.generate(result, all_metrics[name], name, path)
        print(f"  Generated: {path}")

    # 比較レポート
    comparison_path = "data/reports/backtest_comparison.html"
    gen.generate_comparison_report(all_results, all_metrics, comparison_path)
    print(f"  Generated: {comparison_path}")

    # ====== サマリー ======
    print("\n" + "=" * 60)
    print("BACKTEST SUMMARY")
    print("=" * 60)
    print(f"Train: {n_train}, Test: {n_test}, Races: {test_races}, Days: {test_days}")
    print(f"{'Strategy':<20} {'ROI':>8} {'Bets':>6} {'Hit%':>6} {'PF':>6} {'Net Profit':>14}")
    print("-" * 65)
    for name in strategies:
        m = all_metrics[name]
        print(f"{name:<20} {m['roi_pct']:>7.1f}% {m['total_bets']:>6} {m['hit_rate_pct']:>5.1f}% {m['profit_factor']:>6.2f} {m['net_profit']:>+13,.0f}")
    print("=" * 60)


if __name__ == "__main__":
    main()
