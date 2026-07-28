"""オーバーフィッティング検出モジュール"""

from itertools import combinations
from typing import Callable, Dict, List

import numpy as np

from src.utils.config_loader import load_backtest_config
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class OverfitDetector:
    """Detection and quantification of backtest overfitting."""

    @staticmethod
    def cscv(
        backtest_returns: np.ndarray, n_splits: int = 16
    ) -> Dict[str, float]:
        """Combinatorially Symmetric Cross-Validation.

        Split returns into n_splits blocks. For each combination of
        n_splits/2 blocks as in-sample and the rest as out-of-sample,
        compare in-sample rank with out-of-sample performance.

        Args:
            backtest_returns: Array of per-period returns.
            n_splits: Number of blocks to split returns into (must be even).

        Returns:
            Dictionary with 'pbo' (Probability of Backtest Overfitting)
            and 'num_combinations' evaluated.
        """
        backtest_returns = np.asarray(backtest_returns)
        n = len(backtest_returns)
        block_size = n // n_splits
        if block_size == 0:
            logger.warning("Not enough data for CSCV with %d splits", n_splits)
            return {"pbo": 0.0, "num_combinations": 0}

        # Trim to exact multiple
        trimmed = backtest_returns[: block_size * n_splits]
        blocks = np.array_split(trimmed, n_splits)

        half = n_splits // 2
        all_combos = list(combinations(range(n_splits), half))
        overfit_count = 0

        for is_indices in all_combos:
            oos_indices = tuple(i for i in range(n_splits) if i not in is_indices)

            is_returns = np.concatenate([blocks[i] for i in is_indices])
            oos_returns = np.concatenate([blocks[i] for i in oos_indices])

            is_sharpe = (
                is_returns.mean() / is_returns.std()
                if is_returns.std() > 0
                else 0.0
            )
            oos_sharpe = (
                oos_returns.mean() / oos_returns.std()
                if oos_returns.std() > 0
                else 0.0
            )

            # Overfit if in-sample looks good but out-of-sample is negative
            if is_sharpe > 0 and oos_sharpe <= 0:
                overfit_count += 1

        pbo = overfit_count / len(all_combos) if all_combos else 0.0
        logger.info(
            "CSCV: PBO=%.4f (%d/%d combinations)",
            pbo,
            overfit_count,
            len(all_combos),
        )
        return {"pbo": pbo, "num_combinations": len(all_combos)}

    @staticmethod
    def parameter_sensitivity(
        run_backtest_func: Callable,
        base_params: dict,
        param_ranges: List[float] = None,
    ) -> Dict[str, dict]:
        """Vary each parameter by specified percentages and check ROI stability.

        Args:
            run_backtest_func: Callable(params) -> float (ROI).
            base_params: Base parameter dictionary.
            param_ranges: List of variation fractions (e.g. [0.10, 0.20]).

        Returns:
            {param_name: {variation: roi, ...}, is_sensitive: bool}.
        """
        config = load_backtest_config()
        od = config.get("overfit_detection", {})
        if param_ranges is None:
            param_ranges = od.get("param_sensitivity_range", [0.10, 0.20])
        max_variation = od.get("param_sensitivity_max_variation", 0.30)

        base_roi = run_backtest_func(base_params)
        report = {}

        for param_name, base_value in base_params.items():
            if not isinstance(base_value, (int, float)):
                continue

            param_results = {"base": base_roi}
            is_sensitive = False

            for delta in param_ranges:
                for sign in [-1, 1]:
                    factor = 1 + sign * delta
                    modified = dict(base_params)
                    modified[param_name] = type(base_value)(
                        base_value * factor
                    )

                    try:
                        roi = run_backtest_func(modified)
                    except Exception as e:
                        logger.warning(
                            "Sensitivity test failed for %s (%.0f%%): %s",
                            param_name,
                            sign * delta * 100,
                            e,
                        )
                        roi = None

                    label = f"{sign * delta * 100:+.0f}%"
                    param_results[label] = roi

                    if roi is not None and base_roi != 0:
                        change = abs(roi - base_roi) / abs(base_roi)
                        if change > max_variation:
                            is_sensitive = True

            report[param_name] = {
                "results": param_results,
                "is_sensitive": is_sensitive,
            }

        sensitive_params = [k for k, v in report.items() if v["is_sensitive"]]
        if sensitive_params:
            logger.warning("Sensitive parameters detected: %s", sensitive_params)
        else:
            logger.info("No overly sensitive parameters found")

        return report

    @staticmethod
    def bootstrap_test(
        daily_returns: np.ndarray,
        n_iterations: int = 1000,
        confidence: float = 0.95,
    ) -> Dict[str, float]:
        """Bootstrap test for ROI significance.

        Resample daily returns with replacement to build confidence interval.

        Args:
            daily_returns: Array of daily P&L values.
            n_iterations: Number of bootstrap samples.
            confidence: Confidence level for CI.

        Returns:
            Dictionary with mean_roi, ci_lower, ci_upper, prob_profitable.
        """
        daily_returns = np.asarray(daily_returns, dtype=float)
        n = len(daily_returns)
        if n == 0:
            return {
                "mean_roi": 0.0,
                "ci_lower": 0.0,
                "ci_upper": 0.0,
                "prob_profitable": 0.0,
            }

        rng = np.random.default_rng(seed=42)
        bootstrap_totals = []

        for _ in range(n_iterations):
            sample = rng.choice(daily_returns, size=n, replace=True)
            bootstrap_totals.append(sample.sum())

        bootstrap_totals = np.array(bootstrap_totals)
        alpha = (1 - confidence) / 2
        ci_lower = float(np.percentile(bootstrap_totals, alpha * 100))
        ci_upper = float(np.percentile(bootstrap_totals, (1 - alpha) * 100))
        mean_roi = float(bootstrap_totals.mean())
        prob_profitable = float((bootstrap_totals > 0).mean())

        logger.info(
            "Bootstrap: mean=%.0f, CI=[%.0f, %.0f], P(profitable)=%.2f%%",
            mean_roi,
            ci_lower,
            ci_upper,
            prob_profitable * 100,
        )

        return {
            "mean_roi": mean_roi,
            "ci_lower": ci_lower,
            "ci_upper": ci_upper,
            "prob_profitable": prob_profitable,
        }
