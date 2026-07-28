"""改善版バックテスト: validation split + calibration + 市場特徴量モデル"""

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
from src.models.probability_calibrator import ProbabilityCalibrator
from src.utils.config_loader import get_db_path


def estimate_place_odds(win_odds, horse_count):
    if win_odds <= 0:
        return 1.0
    count_factor = min(1.0, horse_count / 18.0) * 0.1 + 0.25
    return max(1.05, win_odds * count_factor)


def run_backtest(test_df, strategy_fn, results_df, payoffs_df, test_races, test_days):
    result = BacktestResult()
    bankroll = 1_000_000
    daily_pnl = {}

    for race_id in test_df["race_id"].unique():
        race_df = test_df[test_df["race_id"] == race_id]
        race_date = str(race_df["race_date"].iloc[0])
        bets = strategy_fn(race_df, bankroll)
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
            daily_pnl.setdefault(race_date, 0.0)
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

    metrics = MetricsCalculator.calculate_all(result, test_races, test_days)
    return result, metrics


def make_place_strategy(min_edge, min_prob, kelly_frac=0.25, max_bets=3):
    def strategy(race_df, bankroll):
        if len(race_df) < 8:
            return []
        candidates = []
        hc = len(race_df)
        for _, row in race_df.iterrows():
            p = row["pred_proba"]
            odds = row.get("odds", 0)
            if p < min_prob or odds < 1.5 or odds <= 0:
                continue
            market_p = min(0.95, 3.0 / odds)
            edge = p - market_p
            if edge < min_edge:
                continue
            po = estimate_place_odds(odds, hc)
            candidates.append({
                "num": int(row["horse_number"]),
                "p": p, "edge": edge, "po": po, "odds": odds,
            })
        if not candidates:
            return []
        candidates.sort(key=lambda x: x["edge"], reverse=True)
        bets = []
        for c in candidates[:max_bets]:
            b = c["po"] - 1
            if b <= 0:
                continue
            kelly = max(0, (c["p"] * b - (1 - c["p"])) / b) * kelly_frac
            amount = max(100, round(bankroll * min(kelly, 0.03) / 100) * 100)
            bets.append(Bet(
                bet_type="\u8907\u52dd", combination=str(c["num"]),
                amount=amount, odds=c["po"],
                expected_value=c["p"] * c["po"],
                horse_numbers=[c["num"]],
            ))
        return bets
    return strategy


def make_win_strategy(min_edge, min_prob, min_odds, max_odds,
                      kelly_frac=0.20, max_bets=2):
    def strategy(race_df, bankroll):
        if len(race_df) < 8:
            return []
        candidates = []
        for _, row in race_df.iterrows():
            p_top3 = row["pred_proba"]
            odds = row.get("odds", 0)
            if p_top3 < min_prob or odds <= 0:
                continue
            if not (min_odds <= odds <= max_odds):
                continue
            if p_top3 > 0.6:
                wr = 0.45
            elif p_top3 > 0.4:
                wr = 0.38
            else:
                wr = 0.30
            p_win = p_top3 * wr
            market_p = 1.0 / odds
            edge = p_win - market_p
            if edge < min_edge:
                continue
            candidates.append({
                "num": int(row["horse_number"]),
                "p_win": p_win, "edge": edge,
                "odds": odds, "ev": p_win * odds,
            })
        if not candidates:
            return []
        candidates.sort(key=lambda x: x["edge"], reverse=True)
        bets = []
        for c in candidates[:max_bets]:
            b = c["odds"] - 1
            if b <= 0:
                continue
            kelly = max(0, (c["p_win"] * b - (1 - c["p_win"])) / b) * kelly_frac
            amount = max(100, round(bankroll * min(kelly, 0.02) / 100) * 100)
            bets.append(Bet(
                bet_type="\u5358\u52dd", combination=str(c["num"]),
                amount=amount, odds=c["odds"],
                expected_value=c["ev"],
                horse_numbers=[c["num"]],
            ))
        return bets
    return strategy


def main():
    db_path = get_db_path()

    # ====== Load ======
    print("=" * 85)
    print("Loading features & training model...")
    features_df = pd.read_pickle("data/features_all.pkl")
    features_df["target"] = (features_df["finish_order"] <= 3).astype(int)

    meta_cols = {"race_id", "race_date", "horse_number", "horse_id",
                 "horse_name", "finish_order", "target", "year"}
    feature_cols = [c for c in features_df.columns if c not in meta_cols]

    # 3-way split
    dates = pd.to_datetime(features_df["race_date"])
    train_mask = dates <= "2023-12-31"
    val_mask = (dates > "2023-12-31") & (dates <= "2024-06-30")
    test_mask = dates > "2024-06-30"

    X_train = features_df[train_mask][feature_cols].fillna(0)
    y_train = features_df[train_mask]["target"]
    X_val = features_df[val_mask][feature_cols].fillna(0)
    y_val = features_df[val_mask]["target"]
    X_test = features_df[test_mask][feature_cols].fillna(0)
    y_test = features_df[test_mask]["target"]

    print(f"Train: {len(X_train)}, Val: {len(X_val)}, Test: {len(X_test)}")

    # Model with early stopping
    model = LGBMModel()
    model.fit(X_train, y_train, X_val, y_val)

    val_proba = model.predict_proba(X_val)
    test_proba = model.predict_proba(X_test)
    print(f"Val AUC: {roc_auc_score(y_val, val_proba):.4f}, "
          f"Test AUC: {roc_auc_score(y_test, test_proba):.4f}")

    # Calibrate
    calibrator = ProbabilityCalibrator("isotonic")
    calibrator.fit(y_val.values, val_proba)
    test_proba_cal = calibrator.calibrate(test_proba)

    test_df = features_df[test_mask].copy()
    test_df["pred_proba"] = test_proba_cal

    # Load payoff data
    conn = sqlite3.connect(db_path, timeout=10)
    results_df = pd.read_sql(
        "SELECT race_id, horse_number, finish_order as finish_position "
        "FROM race_results", conn)
    payoffs_df = pd.read_sql(
        "SELECT race_id, bet_type, combination, payout as payout_amount "
        "FROM payoffs", conn)
    conn.close()

    test_races = test_df["race_id"].nunique()
    test_days = pd.to_datetime(test_df["race_date"]).dt.date.nunique()

    # ====== Strategies ======
    print()
    print("=" * 85)
    print("BACKTEST RESULTS (calibrated model, market features included)")
    print("=" * 85)
    print(f"Test: {test_df['race_date'].min()} ~ {test_df['race_date'].max()}, "
          f"Races: {test_races}, Days: {test_days}")
    print()

    configs = {
        # Place (fukusho)
        "Place e>=0.03 p>=0.30": make_place_strategy(0.03, 0.30, 0.25, 3),
        "Place e>=0.05 p>=0.30": make_place_strategy(0.05, 0.30, 0.25, 3),
        "Place e>=0.05 p>=0.35": make_place_strategy(0.05, 0.35, 0.25, 2),
        "Place e>=0.08 p>=0.30": make_place_strategy(0.08, 0.30, 0.25, 3),
        "Place e>=0.10 p>=0.30": make_place_strategy(0.10, 0.30, 0.20, 3),
        "Place e>=0.10 p>=0.35": make_place_strategy(0.10, 0.35, 0.20, 2),
        "Place e>=0.15 p>=0.35": make_place_strategy(0.15, 0.35, 0.20, 2),
        # Win (tansho)
        "Win e>=0.05 o3-20":    make_win_strategy(0.05, 0.35, 3.0, 20.0, 0.20, 2),
        "Win e>=0.08 o3-30":    make_win_strategy(0.08, 0.35, 3.0, 30.0, 0.20, 2),
        "Win e>=0.10 o3-30":    make_win_strategy(0.10, 0.35, 3.0, 30.0, 0.20, 2),
        "Win e>=0.10 o5-50":    make_win_strategy(0.10, 0.30, 5.0, 50.0, 0.15, 2),
        "Win e>=0.12 o3-30":    make_win_strategy(0.12, 0.35, 3.0, 30.0, 0.20, 1),
        "Win e>=0.15 o3-50":    make_win_strategy(0.15, 0.30, 3.0, 50.0, 0.15, 1),
    }

    header = (f"{'Strategy':<25} {'ROI':>8} {'Bets':>6} {'Hit%':>6} "
              f"{'DWin%':>6} {'Net':>12} {'MaxDD':>8} {'Sharpe':>7}")
    print(header)
    print("-" * len(header))

    all_results = {}
    all_metrics = {}

    for name, strat_fn in configs.items():
        result, metrics = run_backtest(
            test_df, strat_fn, results_df, payoffs_df, test_races, test_days)
        all_results[name] = result
        all_metrics[name] = metrics

        dd = metrics.get("max_drawdown_pct", 0)
        sr = metrics.get("sharpe_ratio", 0)
        roi = metrics["roi_pct"]
        marker = " ***" if roi > 100 else ""
        print(f"{name:<25} {roi:>7.1f}% {metrics['total_bets']:>6} "
              f"{metrics['hit_rate_pct']:>5.1f}% "
              f"{metrics['daily_win_rate_pct']:>5.1f}% "
              f"{metrics['net_profit']:>+11,.0f} "
              f"{dd:>7.1f}% {sr:>6.2f}{marker}")

    print("=" * len(header))

    # Best strategy
    profitable = {k: v for k, v in all_metrics.items()
                  if v["total_bets"] > 0 and v["roi_pct"] > 0}
    if profitable:
        best = max(profitable, key=lambda k: profitable[k]["roi_pct"])
        m = all_metrics[best]
        print(f"\nBest: {best}")
        print(f"  ROI: {m['roi_pct']:.1f}%, Bets: {m['total_bets']}, "
              f"Hit: {m['hit_rate_pct']:.1f}%, Net: {m['net_profit']:+,.0f}")

    # Report
    try:
        from src.reporting.html_report import HTMLReportGenerator
        gen = HTMLReportGenerator()
        gen.generate_comparison_report(
            all_results, all_metrics, "data/reports/v4_comparison.html")
        print("\nReport: data/reports/v4_comparison.html")
    except Exception as e:
        print(f"\nReport skipped: {e}")


if __name__ == "__main__":
    main()
