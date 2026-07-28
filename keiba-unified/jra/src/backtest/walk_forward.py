"""ウォークフォワードバックテスト"""

from typing import Callable, Dict

import pandas as pd

from src.backtest.data_splitter import DataSplitter
from src.backtest.engine import BacktestEngine, BacktestResult
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class WalkForwardBacktest:
    """Walk-forward validation orchestrator."""

    def __init__(
        self,
        engine: BacktestEngine,
        data_splitter: DataSplitter,
        model_factory: Callable,
        strategy,
    ):
        """
        Args:
            engine: BacktestEngine instance.
            data_splitter: DataSplitter instance.
            model_factory: Callable that creates a fresh model instance.
            strategy: Strategy object with generate_bets() method.
        """
        self.engine = engine
        self.data_splitter = data_splitter
        self.model_factory = model_factory
        self.strategy = strategy

    def run(
        self,
        features_df: pd.DataFrame,
        results_df: pd.DataFrame,
        payoffs_df: pd.DataFrame,
    ) -> BacktestResult:
        """Run walk-forward backtest across all time windows.

        Args:
            features_df: Full feature matrix with 'race_date' column.
            results_df: Race results data.
            payoffs_df: Payout data.

        Returns:
            Aggregated BacktestResult across all windows.
        """
        splits = self.data_splitter.walk_forward_split(
            features_df["race_date"]
        )

        aggregated = BacktestResult()

        for i, (train_idx, test_idx) in enumerate(splits):
            logger.info("=== Walk-forward window %d/%d ===", i + 1, len(splits))

            model = self.model_factory()

            window_result = self.engine.run(
                features_df,
                results_df,
                payoffs_df,
                self.strategy,
                model,
                train_idx,
                test_idx,
            )

            aggregated = aggregated.merge(window_result)
            logger.info(
                "Window %d: bets=%d, investment=%.0f, payout=%.0f, roi=%.1f%%",
                i + 1,
                window_result.total_bets,
                window_result.total_investment,
                window_result.total_payout,
                window_result.roi,
            )

        logger.info(
            "Walk-forward complete: total_bets=%d, ROI=%.1f%%",
            aggregated.total_bets,
            aggregated.roi,
        )
        return aggregated

    def run_multiple_strategies(
        self,
        features_df: pd.DataFrame,
        results_df: pd.DataFrame,
        payoffs_df: pd.DataFrame,
        strategies_dict: Dict[str, object],
    ) -> Dict[str, BacktestResult]:
        """Run walk-forward for multiple strategies and return comparison.

        Args:
            features_df: Full feature matrix.
            results_df: Race results.
            payoffs_df: Payout data.
            strategies_dict: {strategy_name: strategy_object}.

        Returns:
            {strategy_name: BacktestResult}.
        """
        results = {}

        for name, strategy in strategies_dict.items():
            logger.info(">>> Running strategy: %s <<<", name)
            self.strategy = strategy
            results[name] = self.run(features_df, results_df, payoffs_df)
            logger.info(
                "Strategy '%s' done: ROI=%.1f%%, bets=%d",
                name,
                results[name].roi,
                results[name].total_bets,
            )

        return results
