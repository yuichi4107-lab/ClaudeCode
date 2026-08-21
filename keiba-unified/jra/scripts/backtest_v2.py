"""改良版バックテスト

根本的な問題を修正:
1. モデルはP(top3)を予測するので、単勝のEV計算にそのまま使わない
2. 複勝に焦点を当て、P(top3)と推定複勝オッズで正しいEVを計算する
3. モデル確率 vs 市場確率の乖離を利用するバリュー戦略
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
from src.backtest.engine import BacktestEngine, BacktestResult, BetRecord
from src.backtest.metrics import MetricsCalculator
from src.reporting.html_report import HTMLReportGenerator
from src.strategies.base_strategy import Bet
from src.utils.config_loader import get_db_path
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


def estimate_place_odds(win_odds: float, horse_count: int) -> float:
    """単勝オッズから複勝オッズを推定する

    複勝オッズは一般的に単勝の25-40%程度。頭数により補正。
    """
    if win_odds <= 0:
        return 1.0
    # 頭数が多いほど複勝オッズは高め
    count_factor = min(1.0, horse_count / 18.0) * 0.1 + 0.25
    place_odds = max(1.05, win_odds * count_factor)
    return place_odds


class SmartValueStrategy:
    """改良版バリュー戦略

    モデルのP(top3)予測を活用して、市場が過小評価している馬を見つけて複勝で購入。
    """

    def __init__(self, min_ev=1.15, min_prob=0.25, max_prob=0.80,
                 odds_min=2.0, odds_max=100.0, min_horses=8,
                 max_bets_per_race=3, bet_fraction=0.02):
        self.min_ev = min_ev
        self.min_prob = min_prob
        self.max_prob = max_prob
        self.odds_min = odds_min
        self.odds_max = odds_max
        self.min_horses = min_horses
        self.max_bets_per_race = max_bets_per_race
        self.bet_fraction = bet_fraction

    def generate_bets(self, race_df, probas, bankroll):
        probas = np.asarray(probas)
        if len(race_df) < self.min_horses:
            return []

        horse_count = len(race_df)
        candidates = []

        for i, (idx, row) in enumerate(race_df.iterrows()):
            prob = probas[i] if i < len(probas) else 0.0
            odds = row.get("odds", 0.0)
            horse_num = int(row.get("horse_number", i + 1))

            if prob < self.min_prob or prob > self.max_prob:
                continue
            if odds <= 0 or not (self.odds_min <= odds <= self.odds_max):
                continue

            # 市場のインプライドP(top3)推定
            # 単勝オッズから: 概算 P(win) ≈ 1/odds, P(top3) ≈ min(1.0, 3/odds)
            implied_p_top3 = min(0.95, 3.0 / odds)

            # モデル vs 市場の乖離
            edge = prob - implied_p_top3

            # 複勝オッズ推定
            place_odds = estimate_place_odds(odds, horse_count)

            # 正しいEV = P(top3) × 複勝オッズ
            ev = prob * place_odds

            if ev >= self.min_ev and edge > 0.0:
                candidates.append({
                    "horse_num": horse_num,
                    "prob": prob,
                    "odds": odds,
                    "place_odds": place_odds,
                    "ev": ev,
                    "edge": edge,
                })

        if not candidates:
            return []

        # エッジが大きい順にソート
        candidates.sort(key=lambda x: x["edge"], reverse=True)
        candidates = candidates[:self.max_bets_per_race]

        bets = []
        for c in candidates:
            # Kelly基準（fractional）
            p = c["prob"]
            q = 1 - p
            b = c["place_odds"] - 1  # net odds
            if b <= 0:
                continue
            kelly = (p * b - q) / b
            kelly = max(0, kelly)
            fraction = kelly * 0.25  # 25% Kelly

            amount = bankroll * min(fraction, self.bet_fraction)
            amount = max(100, round(amount / 100) * 100)  # 100円単位
            amount = min(amount, bankroll * 0.05)  # max 5%

            bets.append(Bet(
                bet_type="複勝",
                combination=str(c["horse_num"]),
                amount=amount,
                odds=c["place_odds"],
                expected_value=c["ev"],
                horse_numbers=[c["horse_num"]],
            ))

        return bets


class SmartWinStrategy:
    """単勝専用バリュー戦略

    P(top3)からP(win)を推定し、単勝オッズとの比較でEVを計算。
    """

    def __init__(self, min_ev=1.25, min_prob=0.35, odds_min=3.0, odds_max=30.0,
                 min_horses=8, max_bets_per_race=2, bet_fraction=0.015):
        self.min_ev = min_ev
        self.min_prob = min_prob
        self.odds_min = odds_min
        self.odds_max = odds_max
        self.min_horses = min_horses
        self.max_bets_per_race = max_bets_per_race
        self.bet_fraction = bet_fraction

    def generate_bets(self, race_df, probas, bankroll):
        probas = np.asarray(probas)
        if len(race_df) < self.min_horses:
            return []

        horse_count = len(race_df)
        candidates = []

        for i, (idx, row) in enumerate(race_df.iterrows()):
            prob_top3 = probas[i] if i < len(probas) else 0.0
            odds = row.get("odds", 0.0)
            horse_num = int(row.get("horse_number", i + 1))

            if prob_top3 < self.min_prob:
                continue
            if odds <= 0 or not (self.odds_min <= odds <= self.odds_max):
                continue

            # P(win) ≈ P(top3) × (1/3) ×補正（確率が高い馬ほどwin率が高い）
            # 上位馬ほどtop3のうちwinの割合が高い
            if prob_top3 > 0.6:
                win_ratio = 0.45  # 上位馬: top3の45%がwin
            elif prob_top3 > 0.4:
                win_ratio = 0.38
            elif prob_top3 > 0.3:
                win_ratio = 0.33
            else:
                win_ratio = 0.28

            p_win = prob_top3 * win_ratio

            # EV = P(win) × odds
            ev = p_win * odds

            # 市場のimplied P(win)
            implied_p_win = 1.0 / odds
            edge = p_win - implied_p_win

            if ev >= self.min_ev and edge > 0.0:
                candidates.append({
                    "horse_num": horse_num,
                    "p_win": p_win,
                    "p_top3": prob_top3,
                    "odds": odds,
                    "ev": ev,
                    "edge": edge,
                })

        if not candidates:
            return []

        candidates.sort(key=lambda x: x["ev"], reverse=True)
        candidates = candidates[:self.max_bets_per_race]

        bets = []
        for c in candidates:
            p = c["p_win"]
            b = c["odds"] - 1
            if b <= 0:
                continue
            kelly = (p * b - (1 - p)) / b
            kelly = max(0, kelly)
            fraction = kelly * 0.20  # 20% Kelly

            amount = bankroll * min(fraction, self.bet_fraction)
            amount = max(100, round(amount / 100) * 100)
            amount = min(amount, bankroll * 0.03)

            bets.append(Bet(
                bet_type="単勝",
                combination=str(c["horse_num"]),
                amount=amount,
                odds=c["odds"],
                expected_value=c["ev"],
                horse_numbers=[c["horse_num"]],
            ))

        return bets


class WideValueStrategy:
    """ワイド（2頭複勝）バリュー戦略

    モデルの上位予測馬2頭の組み合わせでワイドを購入。
    """

    def __init__(self, min_prob_each=0.30, min_combined_prob=0.25,
                 min_horses=10, max_combos=3, bet_fraction=0.015):
        self.min_prob_each = min_prob_each
        self.min_combined_prob = min_combined_prob
        self.min_horses = min_horses
        self.max_combos = max_combos
        self.bet_fraction = bet_fraction

    def generate_bets(self, race_df, probas, bankroll):
        probas = np.asarray(probas)
        if len(race_df) < self.min_horses:
            return []

        # 候補馬を確率順にリスト化
        horse_data = []
        for i, (idx, row) in enumerate(race_df.iterrows()):
            prob = probas[i] if i < len(probas) else 0.0
            odds = row.get("odds", 0.0)
            horse_num = int(row.get("horse_number", i + 1))
            if prob >= self.min_prob_each and odds > 0:
                horse_data.append({"num": horse_num, "prob": prob, "odds": odds})

        if len(horse_data) < 2:
            return []

        horse_data.sort(key=lambda x: x["prob"], reverse=True)

        bets = []
        combo_count = 0
        for i in range(len(horse_data)):
            for j in range(i + 1, len(horse_data)):
                if combo_count >= self.max_combos:
                    break
                h1, h2 = horse_data[i], horse_data[j]
                # P(両方top3) ≈ P1(top3) × P2(top3) × 補正
                # 同じレースなのでtop3の枠は3つ。独立ではないが近似
                combined_prob = h1["prob"] * h2["prob"] * 1.5  # 補正

                if combined_prob < self.min_combined_prob:
                    continue

                # ワイドオッズ推定 (単勝オッズの積の平方根 × 係数)
                wide_odds_est = max(1.5, (h1["odds"] * h2["odds"]) ** 0.5 * 0.3)
                ev = combined_prob * wide_odds_est

                if ev < 1.0:
                    continue

                nums = sorted([h1["num"], h2["num"]])
                combo_str = f"{nums[0]}-{nums[1]}"

                amount = bankroll * self.bet_fraction
                amount = max(100, round(amount / 100) * 100)
                amount = min(amount, bankroll * 0.03)

                bets.append(Bet(
                    bet_type="ワイド",
                    combination=combo_str,
                    amount=amount,
                    odds=wide_odds_est,
                    expected_value=ev,
                    horse_numbers=nums,
                ))
                combo_count += 1
            if combo_count >= self.max_combos:
                break

        return bets


def run_single_strategy(strategy_name, strategy, features_df, results_df, payoffs_df,
                        feature_cols, train_mask, test_mask):
    """1戦略のバックテスト実行"""
    train_df = features_df[train_mask]
    test_df = features_df[test_mask].copy()

    X_train = train_df[feature_cols].fillna(0)
    y_train = train_df["target"]

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

    X_test = test_df[feature_cols].fillna(0)
    probas = model.predict_proba(X_test)
    test_df["pred_proba"] = probas

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

    return result


def main():
    db_path = get_db_path()

    # ====== Phase 1: 特徴量生成 ======
    print("=" * 60)
    print("Phase 1: Building features...")
    print("=" * 60)

    t0 = time.time()
    pipeline = FastFeaturePipeline(db_path)
    features_df = pipeline.build_features("2021-01-01", "2025-12-31")
    elapsed = time.time() - t0

    if features_df.empty:
        print("ERROR: No features generated")
        return

    features_df["target"] = (features_df["finish_order"] <= 3).astype(int)
    print(f"Feature matrix: {features_df.shape} in {elapsed:.1f}s")

    # ====== Phase 2: Train/Test Split ======
    print("\n" + "=" * 60)
    print("Phase 2: Train/Test Split")
    print("=" * 60)

    dates = pd.to_datetime(features_df["race_date"])
    train_mask = dates <= "2024-06-30"
    test_mask = dates > "2024-06-30"

    n_train = train_mask.sum()
    n_test = test_mask.sum()

    if n_test < 50:
        dates_sorted = dates.sort_values()
        cutoff_date = dates_sorted.iloc[int(len(dates_sorted) * 0.8)]
        train_mask = dates <= cutoff_date
        test_mask = dates > cutoff_date
        n_train = train_mask.sum()
        n_test = test_mask.sum()

    print(f"Train: {n_train}, Test: {n_test}")

    meta_cols = {"race_id", "race_date", "horse_number", "horse_id",
                 "horse_name", "finish_order", "target", "pred_proba"}
    feature_cols = [c for c in features_df.columns if c not in meta_cols]

    # 結果・払戻テーブル
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

    test_races = features_df[test_mask]["race_id"].nunique()
    test_days = pd.to_datetime(features_df[test_mask]["race_date"]).dt.date.nunique()

    # ====== Phase 3: 改良版戦略バックテスト ======
    print("\n" + "=" * 60)
    print("Phase 3: Running backtests with improved strategies...")
    print("=" * 60)

    strategies = {
        "Place Value (Conservative)": SmartValueStrategy(
            min_ev=1.20, min_prob=0.30, odds_min=2.0, odds_max=50.0,
            max_bets_per_race=2, bet_fraction=0.02,
        ),
        "Place Value (Aggressive)": SmartValueStrategy(
            min_ev=1.10, min_prob=0.25, odds_min=2.0, odds_max=80.0,
            max_bets_per_race=3, bet_fraction=0.015,
        ),
        "Win Value": SmartWinStrategy(
            min_ev=1.30, min_prob=0.40, odds_min=3.0, odds_max=20.0,
            max_bets_per_race=2, bet_fraction=0.01,
        ),
        "Wide Value": WideValueStrategy(
            min_prob_each=0.30, min_combined_prob=0.20,
            min_horses=10, max_combos=3, bet_fraction=0.01,
        ),
    }

    all_results = {}
    all_metrics = {}

    for name, strategy in strategies.items():
        print(f"\n--- {name} ---")
        t0 = time.time()
        result = run_single_strategy(
            name, strategy, features_df, results_df, payoffs_df,
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
        if metrics['sharpe_ratio'] != 0:
            print(f"  Sharpe: {metrics['sharpe_ratio']:.2f}")
        if metrics['profit_factor'] != float('inf'):
            print(f"  Profit Factor: {metrics['profit_factor']:.2f}")
        print(f"  Time: {elapsed:.1f}s")

        # ベットの詳細統計
        if result.bets:
            hits = [b for b in result.bets if b.is_hit]
            misses = [b for b in result.bets if not b.is_hit]
            if hits:
                avg_win_payout = np.mean([b.payout for b in hits])
                avg_win_amount = np.mean([b.amount for b in hits])
                print(f"  Avg winning payout: {avg_win_payout:,.0f} JPY (bet: {avg_win_amount:,.0f})")
            if misses:
                avg_loss = np.mean([b.amount for b in misses])
                print(f"  Avg losing bet: {avg_loss:,.0f} JPY")

    # ====== Phase 4: レポート ======
    print("\n" + "=" * 60)
    print("Phase 4: Generating reports...")
    print("=" * 60)

    gen = HTMLReportGenerator()
    for name, result in all_results.items():
        safe_name = name.replace(" ", "_").replace("(", "").replace(")", "").lower()
        path = f"data/reports/v2_{safe_name}.html"
        gen.generate(result, all_metrics[name], name, path)
        print(f"  Generated: {path}")

    comparison_path = "data/reports/v2_comparison.html"
    gen.generate_comparison_report(all_results, all_metrics, comparison_path)
    print(f"  Generated: {comparison_path}")

    # ====== サマリー ======
    print("\n" + "=" * 60)
    print("BACKTEST v2 SUMMARY")
    print("=" * 60)
    print(f"Train: {n_train}, Test: {n_test}, Races: {test_races}, Days: {test_days}")
    print(f"{'Strategy':<30} {'ROI':>8} {'Bets':>6} {'Hit%':>6} {'PF':>6} {'Net Profit':>14}")
    print("-" * 75)
    for name in strategies:
        m = all_metrics[name]
        pf = m['profit_factor'] if m['profit_factor'] != float('inf') else 0
        print(f"{name:<30} {m['roi_pct']:>7.1f}% {m['total_bets']:>6} {m['hit_rate_pct']:>5.1f}% {pf:>6.2f} {m['net_profit']:>+13,.0f}")
    print("=" * 75)


if __name__ == "__main__":
    main()
