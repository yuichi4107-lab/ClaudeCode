"""レポート生成スクリプト

Usage:
    python -m scripts.05_generate_report
"""

import json
import os
import sys

import pandas as pd

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.backtest.engine import BacktestResult, BetRecord
from src.reporting.html_report import HTMLReportGenerator
from src.reporting.visualizer import Visualizer
from src.utils.config_loader import get_project_root
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


def load_backtest_results(report_dir: str) -> dict:
    """Load saved backtest results (metrics + equity curves).

    Returns:
        {strategy_name: BacktestResult} (reconstructed from saved data).
    """
    metrics_path = os.path.join(report_dir, "backtest_metrics.json")
    if not os.path.exists(metrics_path):
        logger.error("Metrics file not found: %s", metrics_path)
        sys.exit(1)

    with open(metrics_path, "r", encoding="utf-8") as f:
        all_metrics = json.load(f)

    results = {}
    for name in all_metrics:
        result = BacktestResult()

        # Load equity curve CSV if it exists
        eq_path = os.path.join(report_dir, f"equity_{name}.csv")
        if os.path.exists(eq_path):
            eq_df = pd.read_csv(eq_path, index_col=0, parse_dates=True)
            if isinstance(eq_df, pd.DataFrame):
                result.equity_curve = eq_df.iloc[:, 0]
            else:
                result.equity_curve = eq_df
            result.equity_curve.name = "equity"

            # Reconstruct daily returns from equity curve
            daily_returns = result.equity_curve.diff().dropna()
            daily_returns.name = "daily_return"
            result.daily_returns = daily_returns

        result.total_investment = all_metrics[name].get("total_investment", 0)
        result.total_payout = all_metrics[name].get("total_payout", 0)

        results[name] = result

    return results, all_metrics


def main():
    project_root = get_project_root()
    report_dir = os.path.join(project_root, "data", "reports")

    if not os.path.exists(report_dir):
        logger.error("Report directory not found: %s", report_dir)
        logger.error("Please run 04_run_backtest.py first.")
        sys.exit(1)

    # Load results
    results, all_metrics = load_backtest_results(report_dir)
    logger.info("Loaded results for strategies: %s", list(results.keys()))

    # Generate reports
    generator = HTMLReportGenerator()

    # Individual strategy reports
    for name, result in results.items():
        metrics = all_metrics[name]
        output_path = os.path.join(report_dir, f"report_{name}.html")
        generator.generate(result, metrics, name, output_path)
        logger.info("Generated report: %s", output_path)

    # Comparison report
    if len(results) > 1:
        comparison_path = os.path.join(report_dir, "report_comparison.html")
        generator.generate_comparison_report(results, all_metrics, comparison_path)
        logger.info("Generated comparison report: %s", comparison_path)

    logger.info("Report generation complete.")


if __name__ == "__main__":
    main()
