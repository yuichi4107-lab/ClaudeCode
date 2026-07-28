"""馬連Top2 パラメータ最適化 (Optuna + Walk-Forward予測キャッシュ)

Walk-Forward 47ウィンドウのモデル予測を事前計算し、
Optuna Bayesian最適化で8パラメータを高速探索する。

Usage:
    python scripts/optimize_umaren_top2.py [--n-trials 150] [--holdout 6]
"""

import os
import sys
import time
import json
import sqlite3
import argparse
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import numpy as np
import pandas as pd
import optuna
from optuna.samplers import TPESampler

from src.models.lgbm_model import LGBMModel
from src.models.probability_calibrator import ProbabilityCalibrator
from src.backtest.engine import BacktestEngine, BacktestResult
from src.backtest.metrics import MetricsCalculator
from src.strategies.base_strategy import Bet
from src.utils.config_loader import get_db_path

optuna.logging.set_verbosity(optuna.logging.WARNING)

# ============================================================
# Parameter Search Space
# ============================================================
PARAM_RANGES = {
    "min_prob1":         (0.30, 0.55, 0.05),
    "min_prob2":         (0.20, 0.45, 0.05),
    "min_edge":          (0.00, 0.15, 0.01),
    "bet_fraction":      (0.005, 0.030, 0.005),
    "max_bet_pct":       (0.01, 0.05, 0.01),
    "correction_factor": (1.5, 4.0, 0.25),
    "market_coeff":      (1.0, 3.0, 0.25),
    "prob_cap":          (0.30, 0.70, 0.05),
}

MIN_BETS = 100


# ============================================================
# Fully Parameterized Strategy Factory
# ============================================================
def make_umaren_top2_full(min_prob1, min_prob2, min_edge, bet_fraction,
                          max_bet_pct, correction_factor, market_coeff, prob_cap):
    def strategy(race_df, bankroll):
        if len(race_df) < 8:
            return []
        horses = []
        for _, row in race_df.iterrows():
            horses.append({
                "num": int(row["horse_number"]),
                "prob": row["pred_proba"],
                "odds": row.get("odds", 0),
            })
        horses.sort(key=lambda x: x["prob"], reverse=True)
        if len(horses) < 2:
            return []
        h1, h2 = horses[0], horses[1]
        if h1["prob"] < min_prob1 or h2["prob"] < min_prob2:
            return []
        p_combo = h1["prob"] * h2["prob"] * correction_factor
        p_combo = min(p_combo, prob_cap)
        if h1["odds"] > 0 and h2["odds"] > 0:
            market_p = market_coeff / (h1["odds"] * h2["odds"]) ** 0.5
            market_p = min(market_p, prob_cap)
        else:
            return []
        if p_combo - market_p < min_edge:
            return []
        nums = sorted([h1["num"], h2["num"]])
        combo = f"{nums[0]} - {nums[1]}"
        amount = max(100, round(bankroll * bet_fraction / 100) * 100)
        amount = min(amount, bankroll * max_bet_pct)
        return [Bet(
            bet_type="\u99ac\u9023", combination=combo,
            amount=amount, odds=0, expected_value=p_combo,
            horse_numbers=nums,
        )]
    return strategy


# ============================================================
# Walk-Forward Precomputation
# ============================================================
def precompute_walkforward_predictions(features_df, feature_cols,
                                       train_months=12, test_months=1):
    """Train models for all windows once, return cached test predictions."""
    dates = pd.to_datetime(features_df["race_date"])
    min_date = dates.min()
    max_date = dates.max()

    windows = []
    train_start = min_date
    while True:
        train_end = train_start + pd.DateOffset(months=train_months) - pd.Timedelta(days=1)
        val_start = train_end - pd.DateOffset(months=2) + pd.Timedelta(days=1)
        test_start = train_end + pd.Timedelta(days=1)
        test_end = test_start + pd.DateOffset(months=test_months) - pd.Timedelta(days=1)
        if test_end > max_date:
            break
        windows.append((train_start, val_start, train_end, test_start, test_end))
        train_start += pd.DateOffset(months=test_months)

    print(f"  {len(windows)} windows to precompute")

    cached = []
    for wi, (tr_s, v_s, tr_e, te_s, te_e) in enumerate(windows):
        train_mask = (dates >= tr_s) & (dates < v_s)
        val_mask = (dates >= v_s) & (dates <= tr_e)
        test_mask = (dates >= te_s) & (dates <= te_e)

        if train_mask.sum() < 100 or test_mask.sum() < 10:
            continue

        X_train = features_df[train_mask][feature_cols].fillna(0)
        y_train = features_df[train_mask]["target"]
        X_val = features_df[val_mask][feature_cols].fillna(0)
        y_val = features_df[val_mask]["target"]
        X_test = features_df[test_mask][feature_cols].fillna(0)

        model = LGBMModel()
        model.fit(X_train, y_train, X_val, y_val)

        val_proba = model.predict_proba(X_val)
        calibrator = ProbabilityCalibrator("isotonic")
        calibrator.fit(y_val.values, val_proba)

        test_proba = model.predict_proba(X_test)
        test_proba_cal = calibrator.calibrate(test_proba)

        test_df = features_df[test_mask].copy()
        test_df["pred_proba"] = test_proba_cal

        cached.append({
            "window_idx": wi,
            "period": f"{te_s.strftime('%Y-%m')}",
            "test_df": test_df,
        })

        if (wi + 1) % 10 == 0:
            print(f"    Window {wi + 1}/{len(windows)} done")

    print(f"  Cached {len(cached)} windows")
    return cached


# ============================================================
# Fast Strategy Evaluator
# ============================================================
def evaluate_strategy_fast(cached_windows, strategy_fn, results_df, payoffs_df,
                           total_races, total_days):
    """Evaluate a strategy using precomputed predictions."""
    result = BacktestResult()
    bankroll = 1_000_000
    daily_pnl = {}
    window_metrics = []
    engine = BacktestEngine()

    for cw in cached_windows:
        test_df = cw["test_df"]
        window_invest = 0
        window_payout = 0
        window_bets = 0

        for race_id in test_df["race_id"].unique():
            race_df = test_df[test_df["race_id"] == race_id]
            race_date = str(race_df["race_date"].iloc[0])

            bets = strategy_fn(race_df, bankroll)
            if not bets:
                continue

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
                window_invest += bet.amount
                window_payout += bet.payout
                window_bets += 1
                daily_pnl.setdefault(race_date, 0.0)
                daily_pnl[race_date] += bet.profit

        w_roi = (window_payout / window_invest * 100) if window_invest > 0 else 0
        window_metrics.append({
            "window": cw["window_idx"],
            "period": cw["period"],
            "bets": window_bets,
            "roi": w_roi,
            "pnl": window_payout - window_invest,
            "bankroll": bankroll,
        })

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

    metrics = MetricsCalculator.calculate_all(result, total_races, total_days)
    return metrics, window_metrics


# ============================================================
# Objective Function
# ============================================================
def make_objective(cached_windows, results_df, payoffs_df, total_races, total_days,
                   param_ranges=None):
    if param_ranges is None:
        param_ranges = PARAM_RANGES

    def objective(trial):
        params = {}
        for name, (low, high, step) in param_ranges.items():
            params[name] = trial.suggest_float(name, low, high, step=step)

        # Constraint: min_prob2 <= min_prob1
        if params["min_prob2"] > params["min_prob1"]:
            return -999.0

        strategy_fn = make_umaren_top2_full(**params)
        metrics, window_metrics = evaluate_strategy_fast(
            cached_windows, strategy_fn, results_df, payoffs_df,
            total_races, total_days)

        roi = metrics["roi_pct"]
        n_bets = metrics["total_bets"]
        max_dd = metrics.get("max_drawdown_pct", 100.0)
        sharpe = metrics.get("sharpe_ratio", 0.0)
        net_profit = metrics["net_profit"]

        if n_bets < MIN_BETS:
            return -999.0 + n_bets * 0.01

        active_windows = [w for w in window_metrics if w["bets"] > 0]
        if not active_windows:
            return -999.0
        profit_window_ratio = sum(1 for w in active_windows if w["pnl"] > 0) / len(active_windows)

        score = (
            0.50 * roi
            + 0.20 * sharpe * 10
            - 0.15 * max_dd * 2
            + 0.15 * profit_window_ratio * 100
        )

        trial.set_user_attr("roi_pct", roi)
        trial.set_user_attr("n_bets", n_bets)
        trial.set_user_attr("max_dd_pct", max_dd)
        trial.set_user_attr("sharpe", sharpe)
        trial.set_user_attr("net_profit", net_profit)
        trial.set_user_attr("profit_window_ratio", profit_window_ratio)

        return score

    return objective


# ============================================================
# Sensitivity Analysis
# ============================================================
def sensitivity_analysis(best_params, cached_windows, results_df, payoffs_df,
                         total_races, total_days):
    """Perturb each parameter independently, measure ROI change."""
    perturbations = [0.90, 0.95, 1.00, 1.05, 1.10]
    results = {}

    for param_name, base_value in best_params.items():
        low, high, _ = PARAM_RANGES[param_name]
        param_rois = []
        for mult in perturbations:
            perturbed = dict(best_params)
            perturbed[param_name] = max(low, min(high, base_value * mult))
            strategy_fn = make_umaren_top2_full(**perturbed)
            metrics, _ = evaluate_strategy_fast(
                cached_windows, strategy_fn, results_df, payoffs_df,
                total_races, total_days)
            param_rois.append(metrics["roi_pct"])

        sensitivity = max(param_rois) - min(param_rois)
        results[param_name] = {
            "perturbations": perturbations,
            "rois": param_rois,
            "sensitivity": sensitivity,
            "fragile": sensitivity > 25,
        }

    return results


# ============================================================
# Window Cross-Validation
# ============================================================
def cross_validate_windows(params, cached_windows, results_df, payoffs_df,
                           total_races, total_days, n_folds=5):
    """K-fold CV over walk-forward windows."""
    n = len(cached_windows)
    indices = list(range(n))
    np.random.seed(42)
    np.random.shuffle(indices)
    fold_size = n // n_folds

    fold_rois = []
    for fi in range(n_folds):
        start = fi * fold_size
        end = start + fold_size if fi < n_folds - 1 else n
        fold_idx = set(indices[start:end])
        fold_windows = [cached_windows[i] for i in range(n) if i in fold_idx]

        strategy_fn = make_umaren_top2_full(**params)
        metrics, _ = evaluate_strategy_fast(
            fold_windows, strategy_fn, results_df, payoffs_df,
            total_races, total_days)
        fold_rois.append(metrics["roi_pct"])

    mean_roi = np.mean(fold_rois)
    std_roi = np.std(fold_rois)
    return {
        "fold_rois": fold_rois,
        "mean_roi": mean_roi,
        "std_roi": std_roi,
        "min_roi": np.min(fold_rois),
        "cv_ratio": std_roi / mean_roi if mean_roi > 0 else float("inf"),
    }


# ============================================================
# Main
# ============================================================
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--n-trials", type=int, default=150)
    parser.add_argument("--holdout", type=int, default=6)
    args = parser.parse_args()

    print("=" * 80)
    print("UMAREN TOP2 PARAMETER OPTIMIZATION (Optuna + Walk-Forward Cache)")
    print("=" * 80)

    # ---- Load Data ----
    print("\nPhase 0: Loading data...")
    t0 = time.time()

    features_df = pd.read_pickle("data/features_all.pkl")
    features_df["target"] = (features_df["finish_order"] <= 3).astype(int)

    meta_cols = {"race_id", "race_date", "horse_number", "horse_id",
                 "horse_name", "finish_order", "target", "year"}
    feature_cols = [c for c in features_df.columns if c not in meta_cols]

    db_path = get_db_path()
    conn = sqlite3.connect(db_path, timeout=10)
    results_df = pd.read_sql(
        "SELECT race_id, horse_number, finish_order as finish_position "
        "FROM race_results", conn)
    payoffs_df = pd.read_sql(
        "SELECT race_id, bet_type, combination, payout as payout_amount "
        "FROM payoffs", conn)
    conn.close()

    total_races = features_df["race_id"].nunique()
    total_days = pd.to_datetime(features_df["race_date"]).dt.date.nunique()
    print(f"  {len(features_df)} rows, {total_races} races, {total_days} days")

    # ---- Precompute ----
    print("\nPhase 0.5: Precomputing walk-forward predictions...")
    all_cached = precompute_walkforward_predictions(features_df, feature_cols)
    precomp_time = time.time() - t0
    print(f"  Done in {precomp_time:.0f}s")

    # Split: optimization vs holdout
    n_holdout = args.holdout
    opt_windows = all_cached[:-n_holdout] if n_holdout > 0 else all_cached
    holdout_windows = all_cached[-n_holdout:] if n_holdout > 0 else []
    print(f"  Optimization: {len(opt_windows)} windows, Holdout: {len(holdout_windows)} windows")

    # ---- Phase 1: Coarse Search ----
    print(f"\nPhase 1: Coarse optimization ({args.n_trials} trials)...")
    t1 = time.time()

    sampler1 = TPESampler(n_startup_trials=20, multivariate=True, seed=42)
    study1 = optuna.create_study(
        study_name="umaren_top2_phase1",
        direction="maximize",
        sampler=sampler1,
    )
    objective1 = make_objective(opt_windows, results_df, payoffs_df,
                                total_races, total_days)
    study1.optimize(objective1, n_trials=args.n_trials, show_progress_bar=True)

    best1 = study1.best_trial
    phase1_time = time.time() - t1
    print(f"  Best score: {best1.value:.1f} "
          f"(ROI={best1.user_attrs['roi_pct']:.1f}%, "
          f"Bets={best1.user_attrs['n_bets']}, "
          f"MaxDD={best1.user_attrs['max_dd_pct']:.1f}%, "
          f"Sharpe={best1.user_attrs['sharpe']:.2f})")
    print(f"  Time: {phase1_time:.0f}s")

    # ---- Phase 2: Fine Search ----
    print(f"\nPhase 2: Fine optimization ({args.n_trials} trials)...")
    t2 = time.time()

    # Narrow ranges around Phase 1 best
    narrow_ranges = {}
    for name, (orig_low, orig_high, orig_step) in PARAM_RANGES.items():
        fine_step = orig_step / 2
        center = best1.params[name]
        narrow_low = max(orig_low, center - 4 * orig_step)
        narrow_high = min(orig_high, center + 4 * orig_step)
        narrow_ranges[name] = (narrow_low, narrow_high, fine_step)

    sampler2 = TPESampler(n_startup_trials=15, multivariate=True, seed=123)
    study2 = optuna.create_study(
        study_name="umaren_top2_phase2",
        direction="maximize",
        sampler=sampler2,
    )
    objective2 = make_objective(opt_windows, results_df, payoffs_df,
                                total_races, total_days, narrow_ranges)
    study2.optimize(objective2, n_trials=args.n_trials, show_progress_bar=True)

    best2 = study2.best_trial
    phase2_time = time.time() - t2
    print(f"  Best score: {best2.value:.1f} "
          f"(ROI={best2.user_attrs['roi_pct']:.1f}%, "
          f"Bets={best2.user_attrs['n_bets']}, "
          f"MaxDD={best2.user_attrs['max_dd_pct']:.1f}%, "
          f"Sharpe={best2.user_attrs['sharpe']:.2f})")
    print(f"  Time: {phase2_time:.0f}s")

    # ---- Collect Top 10 ----
    all_trials = study1.trials + study2.trials
    valid_trials = [t for t in all_trials if t.value is not None and t.value > -900]
    valid_trials.sort(key=lambda t: t.value, reverse=True)
    top_trials = valid_trials[:10]

    print("\n" + "=" * 80)
    print("TOP 10 PARAMETER CONFIGURATIONS")
    print("=" * 80)
    header = f"{'Rank':>4} {'Score':>7} {'ROI%':>7} {'Bets':>5} {'MaxDD%':>7} {'Sharpe':>7} {'ProfW%':>7}"
    print(header)
    print("-" * len(header))
    for i, t in enumerate(top_trials):
        a = t.user_attrs
        pw = a.get("profit_window_ratio", 0) * 100
        print(f"{i+1:>4} {t.value:>7.1f} {a['roi_pct']:>7.1f} {a['n_bets']:>5} "
              f"{a['max_dd_pct']:>7.1f} {a['sharpe']:>7.2f} {pw:>6.1f}%")

    best_params = top_trials[0].params
    print(f"\nBest Parameters:")
    for k, v in best_params.items():
        print(f"  {k:<22} = {v}")

    # ---- Sensitivity Analysis ----
    print("\n" + "=" * 80)
    print("SENSITIVITY ANALYSIS (Best Configuration, +/-10%)")
    print("=" * 80)

    sens = sensitivity_analysis(best_params, opt_windows, results_df, payoffs_df,
                                total_races, total_days)
    header_s = f"{'Parameter':<22} {'-10%':>7} {'-5%':>7} {'Base':>7} {'+5%':>7} {'+10%':>7} {'Sens':>6} {'Flag':>8}"
    print(header_s)
    print("-" * len(header_s))
    fragile_count = 0
    for pname, sdata in sens.items():
        rois = sdata["rois"]
        flag = "FRAGILE" if sdata["fragile"] else ""
        if sdata["fragile"]:
            fragile_count += 1
        print(f"{pname:<22} {rois[0]:>7.1f} {rois[1]:>7.1f} {rois[2]:>7.1f} "
              f"{rois[3]:>7.1f} {rois[4]:>7.1f} {sdata['sensitivity']:>6.1f} {flag:>8}")
    print(f"\nFragile parameters: {fragile_count}/8")

    # ---- Cross-Validation ----
    print("\n" + "=" * 80)
    print("CROSS-VALIDATION (5-fold over windows)")
    print("=" * 80)

    cv_results = {}
    for i, t in enumerate(top_trials[:5]):
        cv = cross_validate_windows(t.params, opt_windows, results_df, payoffs_df,
                                    total_races, total_days)
        cv_results[i] = cv
        robust = "ROBUST" if cv["cv_ratio"] < 0.5 and cv["min_roi"] > 80 else "RISKY"
        print(f"  Config #{i+1}: mean={cv['mean_roi']:.1f}%, std={cv['std_roi']:.1f}%, "
              f"min={cv['min_roi']:.1f}%, CV_ratio={cv['cv_ratio']:.2f} -- {robust}")

    # ---- Holdout Validation ----
    if holdout_windows:
        print("\n" + "=" * 80)
        print(f"HOLDOUT VALIDATION (Last {n_holdout} windows)")
        print("=" * 80)

        for i, t in enumerate(top_trials[:5]):
            strategy_fn = make_umaren_top2_full(**t.params)
            # Optimization ROI
            opt_metrics, _ = evaluate_strategy_fast(
                opt_windows, strategy_fn, results_df, payoffs_df,
                total_races, total_days)
            # Holdout ROI
            ho_metrics, ho_wm = evaluate_strategy_fast(
                holdout_windows, strategy_fn, results_df, payoffs_df,
                total_races, total_days)
            delta = ho_metrics["roi_pct"] - opt_metrics["roi_pct"]
            status = "OK" if delta > -30 else "OVERFIT"
            print(f"  Config #{i+1}: Opt ROI={opt_metrics['roi_pct']:.1f}%, "
                  f"Holdout ROI={ho_metrics['roi_pct']:.1f}% "
                  f"(delta={delta:+.1f}) -- {status}")
            if i == 0:
                print(f"    Holdout bets: {ho_metrics['total_bets']}, "
                      f"Net: {ho_metrics['net_profit']:+,.0f}")

    # ---- Full Evaluation with Best Params ----
    print("\n" + "=" * 80)
    print("FULL WALK-FORWARD (ALL WINDOWS) - Best Parameters")
    print("=" * 80)

    strategy_fn = make_umaren_top2_full(**best_params)
    full_metrics, full_wm = evaluate_strategy_fast(
        all_cached, strategy_fn, results_df, payoffs_df,
        total_races, total_days)

    print(f"  ROI: {full_metrics['roi_pct']:.1f}%")
    print(f"  Bets: {full_metrics['total_bets']}")
    print(f"  Hit rate: {full_metrics['hit_rate_pct']:.1f}%")
    print(f"  Net profit: {full_metrics['net_profit']:+,.0f}")
    print(f"  Max drawdown: {full_metrics.get('max_drawdown_pct', 0):.1f}%")
    print(f"  Sharpe: {full_metrics.get('sharpe_ratio', 0):.2f}")

    active = [w for w in full_wm if w["bets"] > 0]
    prof = sum(1 for w in active if w["pnl"] > 0)
    print(f"  Profitable windows: {prof}/{len(active)} ({prof/len(active)*100:.0f}%)")

    # ---- Comparison with Baseline ----
    print("\n  vs Baseline (min_prob1=0.40, min_prob2=0.30, min_edge=0.05):")
    baseline_fn = make_umaren_top2_full(
        min_prob1=0.40, min_prob2=0.30, min_edge=0.05, bet_fraction=0.01,
        max_bet_pct=0.03, correction_factor=2.5, market_coeff=2.0, prob_cap=0.50)
    base_metrics, base_wm = evaluate_strategy_fast(
        all_cached, baseline_fn, results_df, payoffs_df,
        total_races, total_days)
    print(f"  Baseline ROI: {base_metrics['roi_pct']:.1f}%, "
          f"Bets: {base_metrics['total_bets']}, "
          f"Net: {base_metrics['net_profit']:+,.0f}")
    roi_improvement = full_metrics["roi_pct"] - base_metrics["roi_pct"]
    print(f"  Improvement: {roi_improvement:+.1f} percentage points ROI")

    # ---- Save Results ----
    os.makedirs("data/reports", exist_ok=True)
    output = {
        "timestamp": datetime.now().isoformat(),
        "total_trials": len(all_trials),
        "best_params": best_params,
        "best_score": top_trials[0].value,
        "full_metrics": {
            "roi_pct": full_metrics["roi_pct"],
            "total_bets": full_metrics["total_bets"],
            "hit_rate_pct": full_metrics["hit_rate_pct"],
            "net_profit": full_metrics["net_profit"],
            "max_drawdown_pct": full_metrics.get("max_drawdown_pct", 0),
            "sharpe_ratio": full_metrics.get("sharpe_ratio", 0),
        },
        "baseline_metrics": {
            "roi_pct": base_metrics["roi_pct"],
            "total_bets": base_metrics["total_bets"],
            "net_profit": base_metrics["net_profit"],
        },
        "sensitivity": {k: {"sensitivity": v["sensitivity"], "fragile": v["fragile"],
                            "rois": v["rois"]}
                       for k, v in sens.items()},
        "top_10": [
            {"rank": i+1, "params": t.params, "score": t.value,
             "roi_pct": t.user_attrs["roi_pct"],
             "n_bets": t.user_attrs["n_bets"],
             "sharpe": t.user_attrs["sharpe"]}
            for i, t in enumerate(top_trials)
        ],
    }
    json_path = "data/reports/optimize_umaren_top2_results.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=str)
    print(f"\nResults saved to {json_path}")

    total_time = time.time() - t0
    print(f"\nTotal time: {total_time/60:.1f} min")


if __name__ == "__main__":
    main()
