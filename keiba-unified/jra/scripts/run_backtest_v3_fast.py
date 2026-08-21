"""バックテスト v3 高速版: 事前生成済み特徴量を使用"""

import os
import sys
import time
import sqlite3

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from src.models.lgbm_model import LGBMModel
from src.backtest.engine import BacktestEngine, BacktestResult
from src.backtest.metrics import MetricsCalculator
from src.strategies.base_strategy import Bet
from src.utils.config_loader import get_db_path
from src.utils.logger import setup_logger
from scripts.backtest_v3 import (
    PureModelPlaceStrategy,
    PureModelWinStrategy,
    PureModelWideStrategy,
    estimate_place_odds,
    MARKET_FEATURES,
)

logger = setup_logger(__name__)

MODEL_PARAMS = {
    "n_estimators": 500,
    "max_depth": 5,
    "learning_rate": 0.03,
    "num_leaves": 24,
    "min_child_samples": 50,
    "subsample": 0.7,
    "colsample_bytree": 0.6,
    "reg_alpha": 0.5,
    "reg_lambda": 2.0,
    "verbose": -1,
}


def run_strategy(strategy, features_df, results_df, payoffs_df,
                 feature_cols, train_mask, test_mask):
    """1つの戦略をバックテスト実行"""
    train_df = features_df[train_mask]
    test_df = features_df[test_mask].copy()

    X_train = train_df[feature_cols].fillna(0)
    y_train = train_df["target"]

    model = LGBMModel(params=MODEL_PARAMS.copy())
    model.fit(X_train, y_train)

    X_test = test_df[feature_cols].fillna(0)
    probas = model.predict_proba(X_test)
    test_df["pred_proba"] = probas
    auc = roc_auc_score(test_df["target"], probas)

    result = BacktestResult()
    bankroll = 1_000_000
    daily_pnl = {}

    for race_id in test_df["race_id"].unique():
        race_df = test_df[test_df["race_id"] == race_id]
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
            bet.payout = engine._calculate_payout(bet, payoffs_df) if bet.is_hit else 0.0
            bet.profit = bet.payout - bet.amount

            result.bets.append(bet)
            result.total_investment += bet.amount
            result.total_payout += bet.payout
            bankroll += bet.profit

            if race_date not in daily_pnl:
                daily_pnl[race_date] = 0.0
            daily_pnl[race_date] += bet.profit

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

    return result, auc


def main():
    db_path = get_db_path()

    # ====== 特徴量ロード ======
    print("=" * 60)
    print("Loading pre-built features...")
    features_df = pd.read_pickle("data/features_all.pkl")
    features_df["target"] = (features_df["finish_order"] <= 3).astype(int)
    print(f"Feature matrix: {features_df.shape}")

    # ====== Split ======
    dates = pd.to_datetime(features_df["race_date"])
    train_mask = dates <= "2024-06-30"
    test_mask = dates > "2024-06-30"
    print(f"Train: {train_mask.sum()}, Test: {test_mask.sum()}")

    meta_cols = {"race_id", "race_date", "horse_number", "horse_id",
                 "horse_name", "finish_order", "target", "pred_proba", "year"}
    all_feature_cols = [c for c in features_df.columns if c not in meta_cols]
    pure_feature_cols = [c for c in all_feature_cols if c not in MARKET_FEATURES]
    print(f"Pure features: {len(pure_feature_cols)}, All features: {len(all_feature_cols)}")

    # 結果・払戻テーブル
    conn = sqlite3.connect(db_path, timeout=10)
    results_df = pd.read_sql(
        "SELECT race_id, horse_number, finish_order as finish_position FROM race_results", conn)
    payoffs_df = pd.read_sql(
        "SELECT race_id, bet_type, combination, payout as payout_amount FROM payoffs", conn)
    conn.close()

    test_races = features_df[test_mask]["race_id"].nunique()
    test_days = pd.to_datetime(features_df[test_mask]["race_date"]).dt.date.nunique()

    # ====== Phase 3: Pure Model Strategies ======
    print("\n" + "=" * 60)
    print("Phase 3: Pure Model Strategies (no market features)")
    print("=" * 60)

    strategies = {}
    for min_edge in [0.05, 0.10, 0.15, 0.20]:
        strategies[f"Place edge>={min_edge:.2f}"] = PureModelPlaceStrategy(
            min_edge=min_edge, min_prob=0.25, min_odds=2.0, max_bets=3, bet_fraction=0.02)
    for min_edge in [0.05, 0.10, 0.15]:
        strategies[f"Win edge>={min_edge:.2f}"] = PureModelWinStrategy(
            min_edge=min_edge, min_prob=0.35, min_odds=3.0, max_odds=30.0,
            max_bets=2, bet_fraction=0.015)
    strategies["Wide edge>=0.05"] = PureModelWideStrategy(
        min_prob_each=0.30, min_edge_each=0.05)
    strategies["Wide edge>=0.10"] = PureModelWideStrategy(
        min_prob_each=0.30, min_edge_each=0.10)

    all_results = {}
    all_metrics = {}
    start_total = time.time()

    for name, strategy in strategies.items():
        t0 = time.time()
        result, auc = run_strategy(
            strategy, features_df, results_df, payoffs_df,
            pure_feature_cols, train_mask, test_mask)
        elapsed = time.time() - t0

        metrics = MetricsCalculator.calculate_all(result, test_races, test_days)
        all_results[name] = result
        all_metrics[name] = metrics

        print(f"  {name:<25} AUC:{auc:.4f} Bets:{metrics['total_bets']:>5} "
              f"Hit:{metrics['hit_rate_pct']:>5.1f}% ROI:{metrics['roi_pct']:>7.1f}% "
              f"DWin:{metrics['daily_win_rate_pct']:>5.1f}% "
              f"Net:{metrics['net_profit']:>+12,.0f} ({elapsed:.1f}s)")

    # ====== Phase 4: With Market Features ======
    print("\n" + "=" * 60)
    print("Phase 4: With Market Features (comparison)")
    print("=" * 60)

    mkt_strategies = {
        "Place+Mkt edge>=0.10": PureModelPlaceStrategy(
            min_edge=0.10, min_prob=0.25, min_odds=2.0, max_bets=3, bet_fraction=0.02),
        "Win+Mkt edge>=0.10": PureModelWinStrategy(
            min_edge=0.10, min_prob=0.35, min_odds=3.0, max_odds=30.0,
            max_bets=2, bet_fraction=0.015),
    }

    for name, strategy in mkt_strategies.items():
        t0 = time.time()
        result, auc = run_strategy(
            strategy, features_df, results_df, payoffs_df,
            all_feature_cols, train_mask, test_mask)
        elapsed = time.time() - t0

        metrics = MetricsCalculator.calculate_all(result, test_races, test_days)
        all_results[name] = result
        all_metrics[name] = metrics

        print(f"  {name:<25} AUC:{auc:.4f} Bets:{metrics['total_bets']:>5} "
              f"Hit:{metrics['hit_rate_pct']:>5.1f}% ROI:{metrics['roi_pct']:>7.1f}% "
              f"DWin:{metrics['daily_win_rate_pct']:>5.1f}% "
              f"Net:{metrics['net_profit']:>+12,.0f} ({elapsed:.1f}s)")

    total_elapsed = time.time() - start_total

    # ====== サマリー ======
    print("\n" + "=" * 80)
    print("BACKTEST v3 SUMMARY")
    print("=" * 80)
    print(f"Train: {train_mask.sum()}, Test: {test_mask.sum()}, "
          f"Races: {test_races}, Days: {test_days}")
    print(f"Total time: {total_elapsed:.1f}s")
    print()
    header = f"{'Strategy':<25} {'ROI':>8} {'Bets':>6} {'Hit%':>6} {'DWin%':>6} {'Net Profit':>14} {'MaxDD':>10}"
    print(header)
    print("-" * len(header))
    for name in list(strategies.keys()) + list(mkt_strategies.keys()):
        m = all_metrics[name]
        dd = m.get("max_drawdown_pct", 0)
        print(f"  {name:<23} {m['roi_pct']:>7.1f}% {m['total_bets']:>6} "
              f"{m['hit_rate_pct']:>5.1f}% {m['daily_win_rate_pct']:>5.1f}% "
              f"{m['net_profit']:>+13,.0f} {dd:>8.1f}%")
    print("=" * len(header))

    # レポート生成
    try:
        from src.reporting.html_report import HTMLReportGenerator
        print("\nGenerating reports...")
        gen = HTMLReportGenerator()
        comparison_path = "data/reports/v3_comparison.html"
        gen.generate_comparison_report(all_results, all_metrics, comparison_path)
        print(f"  Generated: {comparison_path}")
    except Exception as e:
        print(f"\nReport generation skipped: {e}")


if __name__ == "__main__":
    main()
