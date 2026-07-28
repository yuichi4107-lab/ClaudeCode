"""バックテスト実行スクリプト

Usage:
    python -m scripts.04_run_backtest
"""

import json
import os
import sys

import joblib
import numpy as np
import pandas as pd

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.backtest.anti_overfit import OverfitDetector
from src.backtest.data_splitter import DataSplitter
from src.backtest.engine import BacktestEngine
from src.backtest.metrics import MetricsCalculator
from src.backtest.walk_forward import WalkForwardBacktest
from src.models.lgbm_model import LGBMModel
from src.utils.config_loader import (
    get_project_root,
    load_backtest_config,
    load_strategies_config,
)
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


def load_data(project_root: str):
    """Load features, results, and payoffs data."""
    features_path = os.path.join(project_root, "data", "features.parquet")
    results_path = os.path.join(project_root, "data", "results.parquet")
    payoffs_path = os.path.join(project_root, "data", "payoffs.parquet")

    for path in [features_path, results_path, payoffs_path]:
        if not os.path.exists(path):
            logger.error("Required data file not found: %s", path)
            sys.exit(1)

    features_df = pd.read_parquet(features_path)
    results_df = pd.read_parquet(results_path)
    payoffs_df = pd.read_parquet(payoffs_path)

    logger.info(
        "Data loaded: features=%s, results=%s, payoffs=%s",
        features_df.shape,
        results_df.shape,
        payoffs_df.shape,
    )
    return features_df, results_df, payoffs_df


def load_strategies(strategies_config: dict) -> dict:
    """Import and instantiate all enabled strategies."""
    from src.strategies import (
        ValueBettingStrategy,
        MultiComboStrategy,
        HybridStrategy,
        UpsetHunterStrategy,
    )

    strategies = {}

    if strategies_config.get("strategy_1_value_betting", {}).get("enabled"):
        strategies["value_betting"] = ValueBettingStrategy(strategies_config)

    if strategies_config.get("strategy_2_multi_combo", {}).get("enabled"):
        strategies["multi_combo"] = MultiComboStrategy(strategies_config)

    if strategies_config.get("strategy_3_hybrid", {}).get("enabled"):
        strategies["hybrid"] = HybridStrategy(strategies_config)

    if strategies_config.get("strategy_4_upset_hunter", {}).get("enabled"):
        strategies["upset_hunter"] = UpsetHunterStrategy(strategies_config)

    logger.info("Loaded strategies: %s", list(strategies.keys()))
    return strategies


def print_metrics(name: str, metrics: dict):
    """Print formatted metrics summary."""
    logger.info("=" * 60)
    logger.info("Strategy: %s", name)
    logger.info("-" * 60)
    logger.info("  ROI:                   %8.1f%%", metrics["roi_pct"])
    logger.info("  Hit Rate:              %8.1f%%", metrics["hit_rate_pct"])
    logger.info("  Purchase Rate:         %8.1f%%", metrics["purchase_rate_pct"])
    logger.info("  Daily Win Rate:        %8.1f%%", metrics["daily_win_rate_pct"])
    logger.info("  Max Drawdown:          %8.1f%%", metrics["max_drawdown_pct"])
    logger.info("  Sharpe Ratio:          %8.2f", metrics["sharpe_ratio"])
    logger.info("  Profit Factor:         %8.2f", metrics["profit_factor"])
    logger.info("  Calmar Ratio:          %8.2f", metrics["calmar_ratio"])
    logger.info("  Max Consecutive Loss:  %8d", metrics["consecutive_loss_max"])
    logger.info("  Total Bets:            %8d", metrics["total_bets"])
    logger.info("  Total Investment:      %12.0f", metrics["total_investment"])
    logger.info("  Total Payout:          %12.0f", metrics["total_payout"])
    logger.info("  Net Profit:            %12.0f", metrics["net_profit"])
    logger.info("=" * 60)


def main():
    project_root = get_project_root()
    bt_config = load_backtest_config()
    strat_config = load_strategies_config()

    # ------------------------------------------------------------------
    # 1. Load data
    # ------------------------------------------------------------------
    features_df, results_df, payoffs_df = load_data(project_root)

    # ------------------------------------------------------------------
    # 2. Setup components
    # ------------------------------------------------------------------
    initial_bankroll = strat_config["common"]["initial_bankroll"]
    engine = BacktestEngine(initial_bankroll=initial_bankroll)
    splitter = DataSplitter(bt_config)

    def model_factory():
        return LGBMModel()

    strategies = load_strategies(strat_config)

    # ------------------------------------------------------------------
    # 3. Run walk-forward backtest for all strategies
    # ------------------------------------------------------------------
    wf = WalkForwardBacktest(engine, splitter, model_factory, strategy=None)
    all_results = wf.run_multiple_strategies(
        features_df, results_df, payoffs_df, strategies
    )

    # ------------------------------------------------------------------
    # 4. Calculate and print metrics
    # ------------------------------------------------------------------
    test_dates = features_df["race_date"].unique()
    total_races = features_df["race_id"].nunique()
    total_days = len(test_dates)

    all_metrics = {}
    for name, result in all_results.items():
        metrics = MetricsCalculator.calculate_all(result, total_races, total_days)
        all_metrics[name] = metrics
        print_metrics(name, metrics)

    # Bet type breakdown
    for name, result in all_results.items():
        breakdown = MetricsCalculator.breakdown_by_column(result, "bet_type")
        logger.info("Bet type breakdown for '%s':", name)
        for bt, bt_metrics in breakdown.items():
            logger.info(
                "  %-8s  ROI=%6.1f%%  Hit=%5.1f%%  Bets=%d  Profit=%+.0f",
                bt,
                bt_metrics["roi_pct"],
                bt_metrics["hit_rate_pct"],
                bt_metrics["total_bets"],
                bt_metrics["net_profit"],
            )

    # ------------------------------------------------------------------
    # 5. Overfit detection
    # ------------------------------------------------------------------
    logger.info("--- Overfit Detection ---")
    for name, result in all_results.items():
        if result.daily_returns is None or len(result.daily_returns) == 0:
            logger.info("Skipping overfit detection for '%s' (no daily returns)", name)
            continue

        daily_ret = result.daily_returns.values

        # CSCV
        cscv_result = OverfitDetector.cscv(
            daily_ret, n_splits=bt_config["overfit_detection"]["cscv_splits"]
        )
        threshold = bt_config["overfit_detection"]["pbo_threshold"]
        status = "PASS" if cscv_result["pbo"] < threshold else "FAIL"
        logger.info(
            "  [%s] %s CSCV PBO=%.4f (threshold=%.2f)",
            status, name, cscv_result["pbo"], threshold,
        )

        # Bootstrap
        boot = OverfitDetector.bootstrap_test(
            daily_ret,
            n_iterations=bt_config["overfit_detection"]["bootstrap_iterations"],
            confidence=bt_config["overfit_detection"]["bootstrap_confidence"],
        )
        logger.info(
            "  %s Bootstrap: mean=%.0f, 95%% CI=[%.0f, %.0f], P(profit)=%.1f%%",
            name,
            boot["mean_roi"],
            boot["ci_lower"],
            boot["ci_upper"],
            boot["prob_profitable"] * 100,
        )

    # ------------------------------------------------------------------
    # 6. Save results
    # ------------------------------------------------------------------
    report_dir = os.path.join(project_root, "data", "reports")
    os.makedirs(report_dir, exist_ok=True)

    # Save metrics
    metrics_path = os.path.join(report_dir, "backtest_metrics.json")
    # Convert any numpy types to Python types for JSON serialization
    serializable_metrics = {}
    for name, m in all_metrics.items():
        serializable_metrics[name] = {
            k: float(v) if isinstance(v, (np.floating, float)) else int(v)
            for k, v in m.items()
        }
    with open(metrics_path, "w", encoding="utf-8") as f:
        json.dump(serializable_metrics, f, indent=2, ensure_ascii=False)
    logger.info("Metrics saved to %s", metrics_path)

    # Save equity curves
    for name, result in all_results.items():
        if result.equity_curve is not None:
            eq_path = os.path.join(report_dir, f"equity_{name}.csv")
            result.equity_curve.to_csv(eq_path, header=True)
            logger.info("Equity curve saved: %s", eq_path)

    logger.info("Backtest complete.")


if __name__ == "__main__":
    main()
