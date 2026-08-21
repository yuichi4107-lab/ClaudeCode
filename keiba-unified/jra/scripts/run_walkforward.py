"""Walk-Forward検証: 有望な馬連・三連複・単勝戦略の堅牢性を検証する

12ヶ月訓練 / 1ヶ月テスト のスライディングウィンドウで時系列検証。
各ウィンドウでモデルを再訓練し、未来漏洩なしのリアルな評価を行う。
"""

import os
import sys
import time
import sqlite3
from itertools import combinations

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import numpy as np
import pandas as pd

from src.models.lgbm_model import LGBMModel
from src.models.probability_calibrator import ProbabilityCalibrator
from src.backtest.engine import BacktestEngine, BacktestResult
from src.backtest.metrics import MetricsCalculator
from src.strategies.base_strategy import Bet
from src.utils.config_loader import get_db_path


def estimate_place_odds(win_odds, horse_count):
    if win_odds <= 0:
        return 1.0
    count_factor = min(1.0, horse_count / 18.0) * 0.1 + 0.25
    return max(1.05, win_odds * count_factor)


# ===== 戦略定義 =====

def strat_umaren_axis(race_df, bankroll):
    """馬連 軸1頭流し (e>=0.05, axis>=0.45, partner>=0.30)"""
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
    axis = horses[0]
    if axis["prob"] < 0.45:
        return []
    bets = []
    for partner in horses[1:8]:
        if partner["prob"] < 0.30:
            continue
        p_combo = axis["prob"] * partner["prob"] * 2.5
        p_combo = min(p_combo, 0.5)
        if axis["odds"] > 0 and partner["odds"] > 0:
            market_p = 2.0 / (axis["odds"] * partner["odds"]) ** 0.5
            market_p = min(market_p, 0.5)
        else:
            continue
        edge = p_combo - market_p
        if edge < 0.05:
            continue
        nums = sorted([axis["num"], partner["num"]])
        combo = f"{nums[0]} - {nums[1]}"
        amount = max(100, round(bankroll * 0.008 / 100) * 100)
        amount = min(amount, bankroll * 0.02)
        bets.append(Bet(
            bet_type="\u99ac\u9023", combination=combo,
            amount=amount, odds=0, expected_value=p_combo,
            horse_numbers=nums,
        ))
        if len(bets) >= 2:
            break
    return bets


def strat_umaren_top2(race_df, bankroll):
    """馬連 Top2 (e>=0.05, p1>=0.40, p2>=0.30)"""
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
    h1, h2 = horses[0], horses[1]
    if h1["prob"] < 0.40 or h2["prob"] < 0.30:
        return []
    p_combo = h1["prob"] * h2["prob"] * 2.5
    p_combo = min(p_combo, 0.5)
    if h1["odds"] > 0 and h2["odds"] > 0:
        market_p = 2.0 / (h1["odds"] * h2["odds"]) ** 0.5
        market_p = min(market_p, 0.5)
    else:
        return []
    if p_combo - market_p < 0.05:
        return []
    nums = sorted([h1["num"], h2["num"]])
    combo = f"{nums[0]} - {nums[1]}"
    amount = max(100, round(bankroll * 0.01 / 100) * 100)
    amount = min(amount, bankroll * 0.03)
    return [Bet(
        bet_type="\u99ac\u9023", combination=combo,
        amount=amount, odds=0, expected_value=p_combo,
        horse_numbers=nums,
    )]


def strat_sanrenpuku_top3(race_df, bankroll):
    """三連複 Top3 (e>=0.00, p>=0.25)"""
    if len(race_df) < 10:
        return []
    horses = []
    for _, row in race_df.iterrows():
        horses.append({
            "num": int(row["horse_number"]),
            "prob": row["pred_proba"],
            "odds": row.get("odds", 0),
        })
    horses.sort(key=lambda x: x["prob"], reverse=True)
    top3 = horses[:3]
    if any(h["prob"] < 0.25 for h in top3):
        return []
    p_combo = 1.0
    for h in top3:
        p_combo *= h["prob"]
    p_combo *= 6.0
    p_combo = min(p_combo, 0.3)
    nums = sorted([h["num"] for h in top3])
    combo = f"{nums[0]} - {nums[1]} - {nums[2]}"
    amount = max(100, round(bankroll * 0.008 / 100) * 100)
    amount = min(amount, bankroll * 0.02)
    return [Bet(
        bet_type="\u4e09\u9023\u8907", combination=combo,
        amount=amount, odds=0, expected_value=p_combo,
        horse_numbers=nums,
    )]


def strat_win_edge008(race_df, bankroll):
    """単勝 (e>=0.08, p>=0.35, odds 3-30)"""
    if len(race_df) < 8:
        return []
    candidates = []
    for _, row in race_df.iterrows():
        p_top3 = row["pred_proba"]
        odds = row.get("odds", 0)
        if p_top3 < 0.35 or odds <= 0 or not (3.0 <= odds <= 30.0):
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
        if edge < 0.08:
            continue
        candidates.append({
            "num": int(row["horse_number"]),
            "p_win": p_win, "edge": edge, "odds": odds,
        })
    if not candidates:
        return []
    candidates.sort(key=lambda x: x["edge"], reverse=True)
    bets = []
    for c in candidates[:2]:
        b = c["odds"] - 1
        if b <= 0:
            continue
        kelly = max(0, (c["p_win"] * b - (1 - c["p_win"])) / b) * 0.20
        amount = max(100, round(bankroll * min(kelly, 0.02) / 100) * 100)
        bets.append(Bet(
            bet_type="\u5358\u52dd", combination=str(c["num"]),
            amount=amount, odds=c["odds"], expected_value=c["p_win"] * c["odds"],
            horse_numbers=[c["num"]],
        ))
    return bets


# ===== Walk-Forward Engine =====

def walk_forward_backtest(features_df, results_df, payoffs_df, strategy_fn,
                          feature_cols, train_months=12, test_months=1):
    """Walk-Forward: 各ウィンドウでモデル再訓練+キャリブレーション"""
    dates = pd.to_datetime(features_df["race_date"])
    min_date = dates.min()
    max_date = dates.max()

    windows = []
    train_start = min_date
    while True:
        train_end = train_start + pd.DateOffset(months=train_months) - pd.Timedelta(days=1)
        # validation: train末尾2ヶ月
        val_start = train_end - pd.DateOffset(months=2) + pd.Timedelta(days=1)
        test_start = train_end + pd.Timedelta(days=1)
        test_end = test_start + pd.DateOffset(months=test_months) - pd.Timedelta(days=1)

        if test_end > max_date:
            break
        windows.append((train_start, val_start, train_end, test_start, test_end))
        train_start += pd.DateOffset(months=test_months)

    print(f"  Windows: {len(windows)}")

    result = BacktestResult()
    bankroll = 1_000_000
    daily_pnl = {}
    window_metrics = []

    for wi, (tr_s, v_s, tr_e, te_s, te_e) in enumerate(windows):
        # Split
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

        # Train
        model = LGBMModel()
        model.fit(X_train, y_train, X_val, y_val)

        # Calibrate
        val_proba = model.predict_proba(X_val)
        calibrator = ProbabilityCalibrator("isotonic")
        calibrator.fit(y_val.values, val_proba)

        test_proba = model.predict_proba(X_test)
        test_proba_cal = calibrator.calibrate(test_proba)

        test_df = features_df[test_mask].copy()
        test_df["pred_proba"] = test_proba_cal

        # Bet
        window_invest = 0
        window_payout = 0
        window_bets = 0

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
                window_invest += bet.amount
                window_payout += bet.payout
                window_bets += 1
                daily_pnl.setdefault(race_date, 0.0)
                daily_pnl[race_date] += bet.profit

        w_roi = (window_payout / window_invest * 100) if window_invest > 0 else 0
        window_metrics.append({
            "window": wi + 1,
            "period": f"{te_s.strftime('%Y-%m')}",
            "bets": window_bets,
            "roi": w_roi,
            "pnl": window_payout - window_invest,
            "bankroll": bankroll,
        })

    # Build equity curve
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

    return result, window_metrics


def main():
    db_path = get_db_path()

    print("=" * 90)
    print("WALK-FORWARD VALIDATION")
    print("=" * 90)

    features_df = pd.read_pickle("data/features_all.pkl")
    features_df["target"] = (features_df["finish_order"] <= 3).astype(int)

    meta_cols = {"race_id", "race_date", "horse_number", "horse_id",
                 "horse_name", "finish_order", "target", "year"}
    feature_cols = [c for c in features_df.columns if c not in meta_cols]

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

    strategies = {
        "UM Axis (e>=0.05)":   strat_umaren_axis,
        "UM Top2 (e>=0.05)":   strat_umaren_top2,
        "3F Top3 (e>=0.00)":   strat_sanrenpuku_top3,
        "Win (e>=0.08)":       strat_win_edge008,
    }

    print(f"Data: {features_df['race_date'].min()} ~ {features_df['race_date'].max()}")
    print(f"Total: {len(features_df)} rows, {total_races} races")
    print(f"Walk-Forward: 12mo train + 1mo test, sliding 1mo")
    print()

    all_results = {}
    all_metrics = {}
    all_windows = {}

    for name, strat_fn in strategies.items():
        print(f"--- {name} ---")
        t0 = time.time()
        result, window_metrics = walk_forward_backtest(
            features_df, results_df, payoffs_df, strat_fn, feature_cols,
            train_months=12, test_months=1,
        )
        elapsed = time.time() - t0

        metrics = MetricsCalculator.calculate_all(result, total_races, total_days)
        all_results[name] = result
        all_metrics[name] = metrics
        all_windows[name] = window_metrics

        print(f"  ROI: {metrics['roi_pct']:.1f}%, Bets: {metrics['total_bets']}, "
              f"Hit: {metrics['hit_rate_pct']:.1f}%, "
              f"Net: {metrics['net_profit']:+,.0f}, "
              f"MaxDD: {metrics.get('max_drawdown_pct', 0):.1f}%, "
              f"Time: {elapsed:.1f}s")

        # Window breakdown
        profitable_windows = sum(1 for w in window_metrics if w["pnl"] > 0)
        total_windows = len([w for w in window_metrics if w["bets"] > 0])
        if total_windows > 0:
            print(f"  Profitable windows: {profitable_windows}/{total_windows} "
                  f"({profitable_windows/total_windows*100:.0f}%)")
        print()

    # ====== Summary ======
    print("=" * 90)
    print("WALK-FORWARD SUMMARY (12mo train / 1mo test)")
    print("=" * 90)

    header = (f"{'Strategy':<22} {'ROI':>8} {'Bets':>6} {'Hit%':>6} "
              f"{'DWin%':>6} {'Net':>14} {'MaxDD':>8} {'ProfWin':>8}")
    print(header)
    print("-" * len(header))

    for name in strategies:
        m = all_metrics[name]
        wm = all_windows[name]
        dd = m.get("max_drawdown_pct", 0)
        pw = sum(1 for w in wm if w["pnl"] > 0)
        tw = len([w for w in wm if w["bets"] > 0])
        pw_str = f"{pw}/{tw}" if tw > 0 else "N/A"
        marker = " ***" if m["roi_pct"] > 100 else ""
        print(f"  {name:<20} {m['roi_pct']:>7.1f}% {m['total_bets']:>6} "
              f"{m['hit_rate_pct']:>5.1f}% {m['daily_win_rate_pct']:>5.1f}% "
              f"{m['net_profit']:>+13,.0f} {dd:>7.1f}% {pw_str:>8}{marker}")

    print("=" * len(header))

    # Window detail for best strategy
    print("\n--- Window Detail ---")
    for name in strategies:
        m = all_metrics[name]
        if m["roi_pct"] <= 0:
            continue
        wm = all_windows[name]
        active_windows = [w for w in wm if w["bets"] > 0]
        if not active_windows:
            continue
        print(f"\n{name}:")
        print(f"  {'Period':<10} {'Bets':>5} {'ROI':>8} {'P&L':>12} {'Bankroll':>12}")
        for w in active_windows:
            marker = "+" if w["pnl"] > 0 else ""
            print(f"  {w['period']:<10} {w['bets']:>5} {w['roi']:>7.1f}% "
                  f"{w['pnl']:>+11,.0f} {w['bankroll']:>11,.0f}")

    # Report
    try:
        from src.reporting.html_report import HTMLReportGenerator
        gen = HTMLReportGenerator()
        gen.generate_comparison_report(
            all_results, all_metrics, "data/reports/v6_walkforward.html")
        print("\nReport: data/reports/v6_walkforward.html")
    except Exception as e:
        print(f"\nReport skipped: {e}")


if __name__ == "__main__":
    main()
