"""馬連・三連複バックテスト: モデル予測を使った組み合わせ馬券戦略"""

import os
import sys
import time
import sqlite3

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score
from itertools import combinations

from src.models.lgbm_model import LGBMModel
from src.backtest.engine import BacktestEngine, BacktestResult
from src.backtest.metrics import MetricsCalculator
from src.strategies.base_strategy import Bet
from src.models.probability_calibrator import ProbabilityCalibrator
from src.utils.config_loader import get_db_path


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


# ===== 馬連戦略 =====

def make_umaren_top2(min_prob1, min_prob2, min_edge, bet_fraction=0.01):
    """上位2頭の馬連: モデル予測上位2頭を軸に"""
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

        # 馬連の市場確率を推定: P(h1 in top2) * P(h2 in top2 | h1 in top2)
        # 簡易推定: 2頭とも3着以内の確率をベースに
        p_combo = h1["prob"] * h2["prob"] * 2.5  # 補正係数
        p_combo = min(p_combo, 0.5)

        # 市場オッズから市場確率推定
        if h1["odds"] > 0 and h2["odds"] > 0:
            market_p = 2.0 / (h1["odds"] * h2["odds"]) ** 0.5
            market_p = min(market_p, 0.5)
        else:
            return []

        edge = p_combo - market_p
        if edge < min_edge:
            return []

        nums = sorted([h1["num"], h2["num"]])
        combo = f"{nums[0]} - {nums[1]}"

        amount = max(100, round(bankroll * bet_fraction / 100) * 100)
        amount = min(amount, bankroll * 0.03)

        return [Bet(
            bet_type="\u99ac\u9023",
            combination=combo,
            amount=amount,
            odds=0,
            expected_value=p_combo,
            horse_numbers=nums,
        )]
    return strategy


def make_umaren_axis(min_axis_prob, min_partner_prob, min_edge,
                     max_partners=3, bet_fraction=0.008):
    """軸1頭流し馬連: 予測最上位を軸に上位N頭と組む"""
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

        axis = horses[0]
        if axis["prob"] < min_axis_prob:
            return []

        bets = []
        for partner in horses[1:max_partners + 3]:
            if partner["prob"] < min_partner_prob:
                continue

            p_combo = axis["prob"] * partner["prob"] * 2.5
            p_combo = min(p_combo, 0.5)

            if axis["odds"] > 0 and partner["odds"] > 0:
                market_p = 2.0 / (axis["odds"] * partner["odds"]) ** 0.5
                market_p = min(market_p, 0.5)
            else:
                continue

            edge = p_combo - market_p
            if edge < min_edge:
                continue

            nums = sorted([axis["num"], partner["num"]])
            combo = f"{nums[0]} - {nums[1]}"

            amount = max(100, round(bankroll * bet_fraction / 100) * 100)
            amount = min(amount, bankroll * 0.02)

            bets.append(Bet(
                bet_type="\u99ac\u9023",
                combination=combo,
                amount=amount,
                odds=0,
                expected_value=p_combo,
                horse_numbers=nums,
            ))

            if len(bets) >= max_partners:
                break

        return bets
    return strategy


def make_umaren_box(min_prob, n_horses, min_edge, bet_fraction=0.005):
    """BOX馬連: 上位N頭のBOX"""
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

        top_horses = [h for h in horses[:n_horses + 2] if h["prob"] >= min_prob]
        if len(top_horses) < 2:
            return []
        top_horses = top_horses[:n_horses]

        # 全組み合わせの平均edgeをチェック
        edges = []
        for h1, h2 in combinations(top_horses, 2):
            p_combo = h1["prob"] * h2["prob"] * 2.5
            p_combo = min(p_combo, 0.5)
            if h1["odds"] > 0 and h2["odds"] > 0:
                market_p = 2.0 / (h1["odds"] * h2["odds"]) ** 0.5
                market_p = min(market_p, 0.5)
                edges.append(p_combo - market_p)

        if not edges or np.mean(edges) < min_edge:
            return []

        bets = []
        for h1, h2 in combinations(top_horses, 2):
            nums = sorted([h1["num"], h2["num"]])
            combo = f"{nums[0]} - {nums[1]}"
            amount = max(100, round(bankroll * bet_fraction / 100) * 100)
            amount = min(amount, bankroll * 0.015)

            p_combo = h1["prob"] * h2["prob"] * 2.5
            bets.append(Bet(
                bet_type="\u99ac\u9023",
                combination=combo,
                amount=amount,
                odds=0,
                expected_value=min(p_combo, 0.5),
                horse_numbers=nums,
            ))
        return bets
    return strategy


# ===== 三連複戦略 =====

def make_sanrenpuku_top3(min_prob_each, min_edge, bet_fraction=0.008):
    """上位3頭の三連複1点"""
    def strategy(race_df, bankroll):
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
        if any(h["prob"] < min_prob_each for h in top3):
            return []

        # P(3頭全て3着以内)の推定
        p_combo = 1.0
        for h in top3:
            p_combo *= h["prob"]
        p_combo *= 6.0  # 3! = 6通りの順番
        p_combo = min(p_combo, 0.3)

        # 市場確率推定
        all_odds = [h["odds"] for h in top3 if h["odds"] > 0]
        if len(all_odds) < 3:
            return []
        market_p = 6.0 / (all_odds[0] * all_odds[1] * all_odds[2]) ** (1/3) * 0.5
        market_p = min(market_p, 0.3)

        edge = p_combo - market_p
        if edge < min_edge:
            return []

        nums = sorted([h["num"] for h in top3])
        combo = f"{nums[0]} - {nums[1]} - {nums[2]}"

        amount = max(100, round(bankroll * bet_fraction / 100) * 100)
        amount = min(amount, bankroll * 0.02)

        return [Bet(
            bet_type="\u4e09\u9023\u8907",
            combination=combo,
            amount=amount,
            odds=0,
            expected_value=p_combo,
            horse_numbers=nums,
        )]
    return strategy


def make_sanrenpuku_axis(min_axis_prob, min_partner_prob, min_edge,
                         max_combos=5, bet_fraction=0.005):
    """軸1頭流し三連複: 予測最上位を軸に上位馬から相手を選ぶ"""
    def strategy(race_df, bankroll):
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

        axis = horses[0]
        if axis["prob"] < min_axis_prob:
            return []

        partners = [h for h in horses[1:8] if h["prob"] >= min_partner_prob]
        if len(partners) < 2:
            return []

        bets = []
        for p1, p2 in combinations(partners, 2):
            trio = [axis, p1, p2]
            p_combo = 1.0
            for h in trio:
                p_combo *= h["prob"]
            p_combo *= 6.0
            p_combo = min(p_combo, 0.3)

            all_odds = [h["odds"] for h in trio if h["odds"] > 0]
            if len(all_odds) < 3:
                continue
            market_p = 6.0 / (all_odds[0] * all_odds[1] * all_odds[2]) ** (1/3) * 0.5
            market_p = min(market_p, 0.3)

            edge = p_combo - market_p
            if edge < min_edge:
                continue

            nums = sorted([h["num"] for h in trio])
            combo = f"{nums[0]} - {nums[1]} - {nums[2]}"

            amount = max(100, round(bankroll * bet_fraction / 100) * 100)
            amount = min(amount, bankroll * 0.01)

            bets.append(Bet(
                bet_type="\u4e09\u9023\u8907",
                combination=combo,
                amount=amount,
                odds=0,
                expected_value=p_combo,
                horse_numbers=nums,
            ))

            if len(bets) >= max_combos:
                break

        return bets
    return strategy


def make_sanrenpuku_box(min_prob, n_horses, min_edge, bet_fraction=0.004):
    """BOX三連複: 上位N頭のBOX"""
    def strategy(race_df, bankroll):
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

        top_horses = [h for h in horses[:n_horses + 2] if h["prob"] >= min_prob]
        if len(top_horses) < 3:
            return []
        top_horses = top_horses[:n_horses]

        # 平均edge
        edges = []
        for trio in combinations(top_horses, 3):
            p_combo = 1.0
            for h in trio:
                p_combo *= h["prob"]
            p_combo *= 6.0
            p_combo = min(p_combo, 0.3)

            all_odds = [h["odds"] for h in trio if h["odds"] > 0]
            if len(all_odds) >= 3:
                market_p = 6.0 / (all_odds[0] * all_odds[1] * all_odds[2]) ** (1/3) * 0.5
                market_p = min(market_p, 0.3)
                edges.append(p_combo - market_p)

        if not edges or np.mean(edges) < min_edge:
            return []

        bets = []
        for trio in combinations(top_horses, 3):
            nums = sorted([h["num"] for h in trio])
            combo = f"{nums[0]} - {nums[1]} - {nums[2]}"

            p_combo = 1.0
            for h in trio:
                p_combo *= h["prob"]
            p_combo *= 6.0

            amount = max(100, round(bankroll * bet_fraction / 100) * 100)
            amount = min(amount, bankroll * 0.01)

            bets.append(Bet(
                bet_type="\u4e09\u9023\u8907",
                combination=combo,
                amount=amount,
                odds=0,
                expected_value=min(p_combo, 0.3),
                horse_numbers=nums,
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

    dates = pd.to_datetime(features_df["race_date"])
    train_mask = dates <= "2023-12-31"
    val_mask = (dates > "2023-12-31") & (dates <= "2024-06-30")
    test_mask = dates > "2024-06-30"

    X_train = features_df[train_mask][feature_cols].fillna(0)
    y_train = features_df[train_mask]["target"]
    X_val = features_df[val_mask][feature_cols].fillna(0)
    y_val = features_df[val_mask]["target"]

    print(f"Train: {len(X_train)}, Val: {len(X_val)}, Test: {test_mask.sum()}")

    model = LGBMModel()
    model.fit(X_train, y_train, X_val, y_val)

    val_proba = model.predict_proba(X_val)
    test_proba = model.predict_proba(features_df[test_mask][feature_cols].fillna(0))
    print(f"Val AUC: {roc_auc_score(y_val, val_proba):.4f}, "
          f"Test AUC: {roc_auc_score(features_df[test_mask]['target'], test_proba):.4f}")

    calibrator = ProbabilityCalibrator("isotonic")
    calibrator.fit(y_val.values, val_proba)
    test_proba_cal = calibrator.calibrate(test_proba)

    test_df = features_df[test_mask].copy()
    test_df["pred_proba"] = test_proba_cal

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
    print("=" * 90)
    print("UMAREN (EXACTA) & SANRENPUKU (TRIFECTA) BACKTEST")
    print("=" * 90)
    print(f"Test: {test_df['race_date'].min()} ~ {test_df['race_date'].max()}, "
          f"Races: {test_races}, Days: {test_days}")
    print()

    configs = {
        # === 馬連 ===
        "UM Top2 e>=0.00 p>=.30/.25":   make_umaren_top2(0.30, 0.25, 0.00, 0.01),
        "UM Top2 e>=0.02 p>=.35/.25":   make_umaren_top2(0.35, 0.25, 0.02, 0.01),
        "UM Top2 e>=0.03 p>=.35/.30":   make_umaren_top2(0.35, 0.30, 0.03, 0.01),
        "UM Top2 e>=0.05 p>=.40/.30":   make_umaren_top2(0.40, 0.30, 0.05, 0.01),
        "UM Axis e>=0.00 p>=.35/.20":   make_umaren_axis(0.35, 0.20, 0.00, 3, 0.008),
        "UM Axis e>=0.02 p>=.40/.25":   make_umaren_axis(0.40, 0.25, 0.02, 3, 0.008),
        "UM Axis e>=0.03 p>=.40/.25":   make_umaren_axis(0.40, 0.25, 0.03, 3, 0.008),
        "UM Axis e>=0.05 p>=.45/.30":   make_umaren_axis(0.45, 0.30, 0.05, 2, 0.008),
        "UM Box3 e>=0.00 p>=.30":       make_umaren_box(0.30, 3, 0.00, 0.005),
        "UM Box3 e>=0.02 p>=.30":       make_umaren_box(0.30, 3, 0.02, 0.005),
        "UM Box4 e>=0.00 p>=.25":       make_umaren_box(0.25, 4, 0.00, 0.004),
        "UM Box4 e>=0.02 p>=.25":       make_umaren_box(0.25, 4, 0.02, 0.004),
        # === 三連複 ===
        "3F Top3 e>=0.00 p>=.25":       make_sanrenpuku_top3(0.25, 0.00, 0.008),
        "3F Top3 e>=0.02 p>=.25":       make_sanrenpuku_top3(0.25, 0.02, 0.008),
        "3F Top3 e>=0.03 p>=.30":       make_sanrenpuku_top3(0.30, 0.03, 0.008),
        "3F Top3 e>=0.05 p>=.30":       make_sanrenpuku_top3(0.30, 0.05, 0.008),
        "3F Axis e>=0.00 p>=.35/.20":   make_sanrenpuku_axis(0.35, 0.20, 0.00, 5, 0.005),
        "3F Axis e>=0.02 p>=.40/.20":   make_sanrenpuku_axis(0.40, 0.20, 0.02, 5, 0.005),
        "3F Axis e>=0.03 p>=.40/.25":   make_sanrenpuku_axis(0.40, 0.25, 0.03, 5, 0.005),
        "3F Axis e>=0.05 p>=.45/.25":   make_sanrenpuku_axis(0.45, 0.25, 0.05, 3, 0.005),
        "3F Box4 e>=0.00 p>=.25":       make_sanrenpuku_box(0.25, 4, 0.00, 0.003),
        "3F Box4 e>=0.02 p>=.25":       make_sanrenpuku_box(0.25, 4, 0.02, 0.003),
        "3F Box5 e>=0.00 p>=.20":       make_sanrenpuku_box(0.20, 5, 0.00, 0.002),
        "3F Box5 e>=0.02 p>=.20":       make_sanrenpuku_box(0.20, 5, 0.02, 0.002),
    }

    header = (f"{'Strategy':<30} {'ROI':>8} {'Bets':>6} {'Hit%':>6} "
              f"{'DWin%':>6} {'Net':>12} {'MaxDD':>8}")
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
        roi = metrics["roi_pct"]
        marker = " ***" if roi > 100 else ""
        print(f"  {name:<28} {roi:>7.1f}% {metrics['total_bets']:>6} "
              f"{metrics['hit_rate_pct']:>5.1f}% "
              f"{metrics['daily_win_rate_pct']:>5.1f}% "
              f"{metrics['net_profit']:>+11,.0f} "
              f"{dd:>7.1f}%{marker}")

        # 区切り線
        if name.startswith("UM Box4") and "e>=0.02" in name:
            print("  " + "-" * (len(header) - 2))

    print("=" * len(header))

    # Best
    profitable = {k: v for k, v in all_metrics.items()
                  if v["total_bets"] >= 5 and v["roi_pct"] > 100}
    if profitable:
        best = max(profitable, key=lambda k: profitable[k]["net_profit"])
        m = all_metrics[best]
        print(f"\nBest (>=5 bets): {best}")
        print(f"  ROI: {m['roi_pct']:.1f}%, Bets: {m['total_bets']}, "
              f"Hit: {m['hit_rate_pct']:.1f}%, Net: {m['net_profit']:+,.0f}")

    # Report
    try:
        from src.reporting.html_report import HTMLReportGenerator
        gen = HTMLReportGenerator()
        gen.generate_comparison_report(
            all_results, all_metrics, "data/reports/v5_combo_comparison.html")
        print("\nReport: data/reports/v5_combo_comparison.html")
    except Exception as e:
        print(f"\nReport skipped: {e}")


if __name__ == "__main__":
    main()
