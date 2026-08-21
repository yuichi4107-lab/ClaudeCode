"""バックテスト v3: 市場特徴量除外モデル

モデルを市場データ（オッズ・人気）なしで訓練し、
モデルの独自評価と市場オッズの乖離からバリューベットを見つける。
"""

import os
import sys
import time
import sqlite3

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from src.features.fast_pipeline import FastFeaturePipeline
from src.models.lgbm_model import LGBMModel
from src.backtest.engine import BacktestEngine, BacktestResult
from src.backtest.metrics import MetricsCalculator
from src.reporting.html_report import HTMLReportGenerator
from src.strategies.base_strategy import Bet
from src.utils.config_loader import get_db_path
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

# 市場関連の特徴量（モデル訓練から除外）
MARKET_FEATURES = {
    "odds", "log_odds", "popularity", "implied_probability",
    "odds_gap_1st_2nd", "favorite_strength", "odds_concentration",
    "model_vs_market", "expected_value",
}


def estimate_place_odds(win_odds, horse_count):
    """単勝オッズから複勝オッズを推定"""
    if win_odds <= 0:
        return 1.0
    count_factor = min(1.0, horse_count / 18.0) * 0.1 + 0.25
    return max(1.05, win_odds * count_factor)


class PureModelPlaceStrategy:
    """市場非依存モデルによる複勝バリュー戦略"""

    def __init__(self, min_edge=0.10, min_prob=0.25, min_odds=2.0,
                 max_bets=3, bet_fraction=0.02):
        self.min_edge = min_edge
        self.min_prob = min_prob
        self.min_odds = min_odds
        self.max_bets = max_bets
        self.bet_fraction = bet_fraction

    def generate_bets(self, race_df, probas, bankroll):
        probas = np.asarray(probas)
        if len(race_df) < 8:
            return []

        horse_count = len(race_df)
        candidates = []

        for i, (idx, row) in enumerate(race_df.iterrows()):
            model_prob = probas[i] if i < len(probas) else 0.0
            odds = row.get("odds", 0.0)
            horse_num = int(row.get("horse_number", i + 1))

            if model_prob < self.min_prob or odds < self.min_odds or odds <= 0:
                continue

            # 市場が示すP(top3) ≈ min(0.95, 3/odds)
            market_p_top3 = min(0.95, 3.0 / odds)

            # モデルが市場より高く評価している場合のみ
            edge = model_prob - market_p_top3

            if edge < self.min_edge:
                continue

            place_odds = estimate_place_odds(odds, horse_count)
            ev = model_prob * place_odds

            candidates.append({
                "horse_num": horse_num,
                "model_prob": model_prob,
                "market_p": market_p_top3,
                "edge": edge,
                "odds": odds,
                "place_odds": place_odds,
                "ev": ev,
            })

        if not candidates:
            return []

        candidates.sort(key=lambda x: x["edge"], reverse=True)
        candidates = candidates[:self.max_bets]

        bets = []
        for c in candidates:
            p = c["model_prob"]
            b = c["place_odds"] - 1
            if b <= 0:
                continue
            kelly = max(0, (p * b - (1 - p)) / b)
            fraction = kelly * 0.25

            amount = bankroll * min(fraction, self.bet_fraction)
            amount = max(100, round(amount / 100) * 100)
            amount = min(amount, bankroll * 0.05)

            bets.append(Bet(
                bet_type="複勝",
                combination=str(c["horse_num"]),
                amount=amount,
                odds=c["place_odds"],
                expected_value=c["ev"],
                horse_numbers=[c["horse_num"]],
            ))

        return bets


class PureModelWinStrategy:
    """市場非依存モデルによる単勝バリュー戦略"""

    def __init__(self, min_edge=0.08, min_prob=0.35, min_odds=3.0,
                 max_odds=30.0, max_bets=2, bet_fraction=0.015):
        self.min_edge = min_edge
        self.min_prob = min_prob
        self.min_odds = min_odds
        self.max_odds = max_odds
        self.max_bets = max_bets
        self.bet_fraction = bet_fraction

    def generate_bets(self, race_df, probas, bankroll):
        probas = np.asarray(probas)
        if len(race_df) < 8:
            return []

        candidates = []
        for i, (idx, row) in enumerate(race_df.iterrows()):
            model_prob_top3 = probas[i] if i < len(probas) else 0.0
            odds = row.get("odds", 0.0)
            horse_num = int(row.get("horse_number", i + 1))

            if model_prob_top3 < self.min_prob or odds <= 0:
                continue
            if not (self.min_odds <= odds <= self.max_odds):
                continue

            # P(win) 推定
            if model_prob_top3 > 0.6:
                win_ratio = 0.45
            elif model_prob_top3 > 0.4:
                win_ratio = 0.38
            else:
                win_ratio = 0.30

            p_win = model_prob_top3 * win_ratio
            market_p_win = 1.0 / odds
            edge = p_win - market_p_win

            if edge < self.min_edge:
                continue

            ev = p_win * odds

            candidates.append({
                "horse_num": horse_num,
                "p_win": p_win,
                "market_p": market_p_win,
                "edge": edge,
                "odds": odds,
                "ev": ev,
            })

        if not candidates:
            return []

        candidates.sort(key=lambda x: x["edge"], reverse=True)
        candidates = candidates[:self.max_bets]

        bets = []
        for c in candidates:
            p = c["p_win"]
            b = c["odds"] - 1
            if b <= 0:
                continue
            kelly = max(0, (p * b - (1 - p)) / b)
            fraction = kelly * 0.20

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


class PureModelWideStrategy:
    """市場非依存モデルによるワイド戦略"""

    def __init__(self, min_prob_each=0.30, min_edge_each=0.05,
                 min_horses=10, max_combos=3, bet_fraction=0.01):
        self.min_prob_each = min_prob_each
        self.min_edge_each = min_edge_each
        self.min_horses = min_horses
        self.max_combos = max_combos
        self.bet_fraction = bet_fraction

    def generate_bets(self, race_df, probas, bankroll):
        probas = np.asarray(probas)
        if len(race_df) < self.min_horses:
            return []

        candidates = []
        for i, (idx, row) in enumerate(race_df.iterrows()):
            prob = probas[i] if i < len(probas) else 0.0
            odds = row.get("odds", 0.0)
            horse_num = int(row.get("horse_number", i + 1))

            if prob < self.min_prob_each or odds <= 0:
                continue

            market_p = min(0.95, 3.0 / odds)
            edge = prob - market_p

            if edge >= self.min_edge_each:
                candidates.append({"num": horse_num, "prob": prob,
                                   "odds": odds, "edge": edge})

        if len(candidates) < 2:
            return []

        candidates.sort(key=lambda x: x["edge"], reverse=True)

        bets = []
        combo_count = 0
        for i in range(min(len(candidates), 4)):
            for j in range(i + 1, min(len(candidates), 5)):
                if combo_count >= self.max_combos:
                    break
                h1, h2 = candidates[i], candidates[j]
                combined_prob = h1["prob"] * h2["prob"] * 1.5

                nums = sorted([h1["num"], h2["num"]])
                combo_str = f"{nums[0]}-{nums[1]}"

                amount = bankroll * self.bet_fraction
                amount = max(100, round(amount / 100) * 100)
                amount = min(amount, bankroll * 0.02)

                wide_odds_est = max(1.5, (h1["odds"] * h2["odds"]) ** 0.5 * 0.3)

                bets.append(Bet(
                    bet_type="ワイド",
                    combination=combo_str,
                    amount=amount,
                    odds=wide_odds_est,
                    expected_value=combined_prob * wide_odds_est,
                    horse_numbers=nums,
                ))
                combo_count += 1
            if combo_count >= self.max_combos:
                break

        return bets


def run_strategy(strategy, features_df, results_df, payoffs_df,
                 feature_cols, train_mask, test_mask, model_params=None):
    """バックテスト実行（モデルは共通パラメータ）"""
    train_df = features_df[train_mask]
    test_df = features_df[test_mask].copy()

    X_train = train_df[feature_cols].fillna(0)
    y_train = train_df["target"]

    params = model_params or {
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
    model = LGBMModel(params=params)
    model.fit(X_train, y_train)

    X_test = test_df[feature_cols].fillna(0)
    probas = model.predict_proba(X_test)
    test_df["pred_proba"] = probas

    # AUC報告
    y_test = test_df["target"]
    auc = roc_auc_score(y_test, probas)

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

    return result, auc


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

    # ====== Phase 2: Split ======
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

    # 特徴量列（市場特徴量を除外）
    meta_cols = {"race_id", "race_date", "horse_number", "horse_id",
                 "horse_name", "finish_order", "target", "pred_proba"}

    all_feature_cols = [c for c in features_df.columns if c not in meta_cols]
    pure_feature_cols = [c for c in all_feature_cols if c not in MARKET_FEATURES]

    print(f"All features: {len(all_feature_cols)}")
    print(f"Pure features (no market): {len(pure_feature_cols)}")

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

    # ====== Phase 3: 複数パラメータ設定でテスト ======
    print("\n" + "=" * 60)
    print("Phase 3: Pure Model Strategies (no market features)")
    print("=" * 60)

    # 強い正則化パラメータ
    model_params = {
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

    strategies = {}

    # 複勝戦略（異なるedge閾値）
    for min_edge in [0.05, 0.10, 0.15, 0.20]:
        name = f"Place edge>={min_edge:.2f}"
        strategies[name] = PureModelPlaceStrategy(
            min_edge=min_edge, min_prob=0.25, min_odds=2.0,
            max_bets=3, bet_fraction=0.02,
        )

    # 単勝戦略
    for min_edge in [0.05, 0.10, 0.15]:
        name = f"Win edge>={min_edge:.2f}"
        strategies[name] = PureModelWinStrategy(
            min_edge=min_edge, min_prob=0.35, min_odds=3.0,
            max_odds=30.0, max_bets=2, bet_fraction=0.015,
        )

    # ワイド戦略
    strategies["Wide edge>=0.05"] = PureModelWideStrategy(
        min_prob_each=0.30, min_edge_each=0.05,
        min_horses=10, max_combos=3, bet_fraction=0.01,
    )
    strategies["Wide edge>=0.10"] = PureModelWideStrategy(
        min_prob_each=0.30, min_edge_each=0.10,
        min_horses=10, max_combos=3, bet_fraction=0.01,
    )

    all_results = {}
    all_metrics = {}

    for name, strategy in strategies.items():
        print(f"\n--- {name} ---")
        t0 = time.time()
        result, auc = run_strategy(
            strategy, features_df, results_df, payoffs_df,
            pure_feature_cols, train_mask, test_mask, model_params
        )
        elapsed = time.time() - t0

        metrics = MetricsCalculator.calculate_all(result, test_races, test_days)
        all_results[name] = result
        all_metrics[name] = metrics

        print(f"  AUC: {auc:.4f}, Bets: {metrics['total_bets']}, "
              f"Hit: {metrics['hit_rate_pct']:.1f}%, ROI: {metrics['roi_pct']:.1f}%, "
              f"DailyWin: {metrics['daily_win_rate_pct']:.1f}%, "
              f"Net: {metrics['net_profit']:+,.0f}, Time: {elapsed:.1f}s")

        if result.bets:
            hits = [b for b in result.bets if b.is_hit]
            if hits:
                avg_payout_ratio = np.mean([b.payout / b.amount for b in hits])
                print(f"  Avg payout ratio: {avg_payout_ratio:.2f}x")

    # ====== Phase 4: With market features (比較用) ======
    print("\n" + "=" * 60)
    print("Phase 4: With Market Features (comparison)")
    print("=" * 60)

    mkt_strategies = {
        "Place+Mkt edge>=0.10": PureModelPlaceStrategy(
            min_edge=0.10, min_prob=0.25, min_odds=2.0,
            max_bets=3, bet_fraction=0.02,
        ),
        "Win+Mkt edge>=0.10": PureModelWinStrategy(
            min_edge=0.10, min_prob=0.35, min_odds=3.0,
            max_odds=30.0, max_bets=2, bet_fraction=0.015,
        ),
    }

    for name, strategy in mkt_strategies.items():
        print(f"\n--- {name} ---")
        t0 = time.time()
        result, auc = run_strategy(
            strategy, features_df, results_df, payoffs_df,
            all_feature_cols, train_mask, test_mask, model_params
        )
        elapsed = time.time() - t0

        metrics = MetricsCalculator.calculate_all(result, test_races, test_days)
        all_results[name] = result
        all_metrics[name] = metrics

        print(f"  AUC: {auc:.4f}, Bets: {metrics['total_bets']}, "
              f"Hit: {metrics['hit_rate_pct']:.1f}%, ROI: {metrics['roi_pct']:.1f}%, "
              f"DailyWin: {metrics['daily_win_rate_pct']:.1f}%, "
              f"Net: {metrics['net_profit']:+,.0f}, Time: {elapsed:.1f}s")

    # ====== サマリー ======
    print("\n" + "=" * 60)
    print("BACKTEST v3 SUMMARY")
    print("=" * 60)
    print(f"Train: {n_train}, Test: {n_test}, Races: {test_races}, Days: {test_days}")
    print(f"{'Strategy':<25} {'ROI':>8} {'Bets':>6} {'Hit%':>6} {'DWin%':>6} {'Net Profit':>14}")
    print("-" * 70)
    for name in list(strategies.keys()) + list(mkt_strategies.keys()):
        m = all_metrics[name]
        print(f"{name:<25} {m['roi_pct']:>7.1f}% {m['total_bets']:>6} "
              f"{m['hit_rate_pct']:>5.1f}% {m['daily_win_rate_pct']:>5.1f}% "
              f"{m['net_profit']:>+13,.0f}")
    print("=" * 70)

    # レポート生成
    print("\nGenerating reports...")
    gen = HTMLReportGenerator()
    comparison_path = "data/reports/v3_comparison.html"
    gen.generate_comparison_report(all_results, all_metrics, comparison_path)
    print(f"  Generated: {comparison_path}")

    # ベスト戦略の個別レポート
    best_name = max(all_metrics, key=lambda k: all_metrics[k]["roi_pct"] if all_metrics[k]["total_bets"] > 0 else -999)
    if all_metrics[best_name]["total_bets"] > 0:
        safe_name = best_name.replace(" ", "_").replace(">=", "").replace(".", "").lower()
        best_path = f"data/reports/v3_best_{safe_name}.html"
        gen.generate(all_results[best_name], all_metrics[best_name], best_name, best_path)
        print(f"  Best strategy: {best_name}")
        print(f"  Generated: {best_path}")


if __name__ == "__main__":
    main()
