"""時系列データ分割モジュール"""

from typing import List, Tuple

import pandas as pd

from src.utils.config_loader import load_backtest_config
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class DataSplitter:
    """Time-series aware data splitting for walk-forward validation."""

    def __init__(self, config: dict = None):
        self.config = config or load_backtest_config()

    def walk_forward_split(
        self,
        dates_series: pd.Series,
        train_months: int = None,
        test_months: int = None,
        slide_months: int = None,
    ) -> List[Tuple[pd.Index, pd.Index]]:
        """Generate walk-forward train/test splits.

        Args:
            dates_series: Series of datetime values (or date strings) aligned
                with the feature DataFrame index.
            train_months: Number of months in training window.
            test_months: Number of months in test window.
            slide_months: Number of months to slide forward each step.

        Returns:
            List of (train_index, test_index) pairs.
        """
        wf = self.config["walk_forward"]
        train_months = train_months or wf["train_months"]
        test_months = test_months or wf["test_months"]
        slide_months = slide_months or wf["slide_months"]

        dates = pd.to_datetime(dates_series)
        min_date = dates.min()
        max_date = dates.max()

        splits = []
        train_start = min_date

        while True:
            train_end = train_start + pd.DateOffset(months=train_months) - pd.Timedelta(days=1)
            test_start = train_end + pd.Timedelta(days=1)
            test_end = test_start + pd.DateOffset(months=test_months) - pd.Timedelta(days=1)

            if test_end > max_date:
                break

            train_mask = (dates >= train_start) & (dates <= train_end)
            test_mask = (dates >= test_start) & (dates <= test_end)

            train_idx = dates_series.index[train_mask]
            test_idx = dates_series.index[test_mask]

            if len(train_idx) > 0 and len(test_idx) > 0:
                splits.append((train_idx, test_idx))
                logger.info(
                    "Window %d: train %s~%s (%d), test %s~%s (%d)",
                    len(splits),
                    train_start.strftime("%Y-%m"),
                    train_end.strftime("%Y-%m"),
                    len(train_idx),
                    test_start.strftime("%Y-%m"),
                    test_end.strftime("%Y-%m"),
                    len(test_idx),
                )

            train_start += pd.DateOffset(months=slide_months)

        logger.info("Generated %d walk-forward splits", len(splits))
        return splits

    def train_val_test_split(
        self, dates_series: pd.Series
    ) -> Tuple[pd.Index, pd.Index, pd.Index]:
        """Split into train / validation / final-test based on config dates.

        Returns:
            (train_idx, val_idx, test_idx)
        """
        ds = self.config["data_split"]
        dates = pd.to_datetime(dates_series)

        train_mask = (dates >= ds["train_start"]) & (dates <= ds["train_end"])
        val_mask = (dates >= ds["validation_start"]) & (
            dates <= ds["validation_end"]
        )
        test_mask = (dates >= ds["final_test_start"]) & (
            dates <= ds["final_test_end"]
        )

        train_idx = dates_series.index[train_mask]
        val_idx = dates_series.index[val_mask]
        test_idx = dates_series.index[test_mask]

        logger.info(
            "Split: train=%d, val=%d, test=%d",
            len(train_idx),
            len(val_idx),
            len(test_idx),
        )
        return train_idx, val_idx, test_idx
