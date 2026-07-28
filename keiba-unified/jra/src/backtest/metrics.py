"""バックテスト評価指標計算モジュール"""

import numpy as np
import pandas as pd

from src.backtest.engine import BacktestResult


class MetricsCalculator:
    """Calculate evaluation metrics from backtest results."""

    @staticmethod
    def calculate_all(
        result: BacktestResult, total_races: int, total_days: int
    ) -> dict:
        """Calculate all metrics from a BacktestResult.

        Args:
            result: BacktestResult from backtest run.
            total_races: Total number of races in the test period.
            total_days: Total number of racing days in the test period.

        Returns:
            Dictionary of computed metrics.
        """
        total_bets = result.total_bets
        winning_bets = result.winning_bets

        # Unique races where bets were placed
        purchased_races = len(set(b.race_id for b in result.bets))

        # Daily win rate
        daily_win_rate = 0.0
        if result.daily_returns is not None and len(result.daily_returns) > 0:
            daily_win_rate = MetricsCalculator.calculate_daily_win_rate(
                result.daily_returns
            )

        # Max drawdown
        max_dd = 0.0
        if result.equity_curve is not None and len(result.equity_curve) > 0:
            max_dd = MetricsCalculator.calculate_max_drawdown(
                result.equity_curve
            )

        # Sharpe
        sharpe = 0.0
        if result.daily_returns is not None and len(result.daily_returns) > 0:
            sharpe = MetricsCalculator.calculate_sharpe_ratio(
                result.daily_returns
            )

        # Profit factor
        gross_profit = sum(b.profit for b in result.bets if b.profit > 0)
        gross_loss = abs(sum(b.profit for b in result.bets if b.profit < 0))
        profit_factor = (
            gross_profit / gross_loss if gross_loss > 0 else float("inf")
        )

        # Calmar ratio
        calmar = 0.0
        if max_dd > 0 and result.net_profit != 0:
            calmar = result.net_profit / max_dd

        # Consecutive losses
        consecutive_loss_max = MetricsCalculator._max_consecutive_losses(
            result.bets
        )

        return {
            "roi_pct": result.roi,
            "hit_rate_pct": result.hit_rate,
            "purchase_rate_pct": (
                purchased_races / total_races * 100 if total_races > 0 else 0.0
            ),
            "daily_win_rate_pct": daily_win_rate,
            "max_drawdown_pct": max_dd,
            "sharpe_ratio": sharpe,
            "profit_factor": profit_factor,
            "calmar_ratio": calmar,
            "consecutive_loss_max": consecutive_loss_max,
            "total_bets": total_bets,
            "winning_bets": winning_bets,
            "total_investment": result.total_investment,
            "total_payout": result.total_payout,
            "net_profit": result.net_profit,
        }

    @staticmethod
    def calculate_max_drawdown(equity_curve: pd.Series) -> float:
        """Max drawdown percentage from equity curve."""
        peak = equity_curve.expanding().max()
        drawdown = (equity_curve - peak) / peak
        return float(abs(drawdown.min()) * 100) if len(drawdown) > 0 else 0.0

    @staticmethod
    def calculate_sharpe_ratio(
        daily_returns: pd.Series, risk_free_rate: float = 0.0
    ) -> float:
        """Annualized Sharpe ratio from daily returns."""
        if len(daily_returns) < 2:
            return 0.0
        excess = daily_returns - risk_free_rate
        std = excess.std()
        if std == 0:
            return 0.0
        # Annualize: horse racing ~288 days/year (JRA typically ~288 racing days)
        annualization_factor = np.sqrt(288)
        return float(excess.mean() / std * annualization_factor)

    @staticmethod
    def calculate_daily_win_rate(daily_returns: pd.Series) -> float:
        """Percentage of profitable days."""
        if len(daily_returns) == 0:
            return 0.0
        profitable = (daily_returns > 0).sum()
        return float(profitable / len(daily_returns) * 100)

    @staticmethod
    def _max_consecutive_losses(bets: list) -> int:
        """Maximum streak of consecutive losing bets."""
        max_streak = 0
        current = 0
        for bet in bets:
            if not bet.is_hit:
                current += 1
                max_streak = max(max_streak, current)
            else:
                current = 0
        return max_streak

    @staticmethod
    def breakdown_by_column(
        result: BacktestResult, column_name: str
    ) -> dict:
        """Break down metrics by a grouping column.

        Requires that BetRecord has the specified attribute or that
        bets are augmented with extra metadata.

        Args:
            result: BacktestResult.
            column_name: Attribute name on BetRecord or key prefix to group by.

        Returns:
            {group_value: {roi_pct, hit_rate_pct, total_bets, net_profit}}.
        """
        groups = {}
        for bet in result.bets:
            key = getattr(bet, column_name, "unknown")
            if key not in groups:
                groups[key] = {
                    "investment": 0.0,
                    "payout": 0.0,
                    "hits": 0,
                    "count": 0,
                }
            groups[key]["investment"] += bet.amount
            groups[key]["payout"] += bet.payout
            groups[key]["count"] += 1
            if bet.is_hit:
                groups[key]["hits"] += 1

        breakdown = {}
        for key, g in groups.items():
            roi = g["payout"] / g["investment"] * 100 if g["investment"] > 0 else 0.0
            hit_rate = g["hits"] / g["count"] * 100 if g["count"] > 0 else 0.0
            breakdown[key] = {
                "roi_pct": roi,
                "hit_rate_pct": hit_rate,
                "total_bets": g["count"],
                "net_profit": g["payout"] - g["investment"],
            }
        return breakdown
