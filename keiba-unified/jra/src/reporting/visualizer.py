"""バックテスト結果可視化モジュール"""

import base64
import io

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import pandas as pd


# Use a clean style
plt.rcParams.update({
    "font.size": 10,
    "axes.titlesize": 12,
    "axes.labelsize": 10,
    "figure.figsize": (10, 5),
    "figure.dpi": 100,
})


class Visualizer:
    """Generate matplotlib charts for backtest results."""

    @staticmethod
    def plot_equity_curve(equity_curve: pd.Series, title: str = "Equity Curve"):
        """Line plot of cumulative equity over time.

        Args:
            equity_curve: pd.Series with datetime index and equity values.
            title: Chart title.

        Returns:
            matplotlib Figure.
        """
        fig, ax = plt.subplots(figsize=(10, 5))
        ax.plot(equity_curve.index, equity_curve.values, linewidth=1.5, color="#2196F3")
        ax.axhline(y=equity_curve.iloc[0], color="gray", linestyle="--", alpha=0.5, label="Initial")
        ax.fill_between(
            equity_curve.index,
            equity_curve.iloc[0],
            equity_curve.values,
            where=equity_curve.values >= equity_curve.iloc[0],
            alpha=0.15,
            color="green",
        )
        ax.fill_between(
            equity_curve.index,
            equity_curve.iloc[0],
            equity_curve.values,
            where=equity_curve.values < equity_curve.iloc[0],
            alpha=0.15,
            color="red",
        )
        ax.set_title(title)
        ax.set_xlabel("Date")
        ax.set_ylabel("Equity (JPY)")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
        ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
        fig.autofmt_xdate()
        ax.legend()
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        return fig

    @staticmethod
    def plot_drawdown(equity_curve: pd.Series, title: str = "Drawdown"):
        """Drawdown percentage chart.

        Args:
            equity_curve: pd.Series with datetime index and equity values.
            title: Chart title.

        Returns:
            matplotlib Figure.
        """
        peak = equity_curve.expanding().max()
        drawdown = (equity_curve - peak) / peak * 100

        fig, ax = plt.subplots(figsize=(10, 4))
        ax.fill_between(drawdown.index, 0, drawdown.values, color="#F44336", alpha=0.4)
        ax.plot(drawdown.index, drawdown.values, color="#F44336", linewidth=0.8)
        ax.set_title(title)
        ax.set_xlabel("Date")
        ax.set_ylabel("Drawdown (%)")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
        ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
        fig.autofmt_xdate()
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        return fig

    @staticmethod
    def plot_daily_returns(daily_returns: pd.Series, title: str = "Daily Returns Distribution"):
        """Histogram of daily returns.

        Args:
            daily_returns: pd.Series of daily P&L.
            title: Chart title.

        Returns:
            matplotlib Figure.
        """
        fig, ax = plt.subplots(figsize=(8, 5))
        values = daily_returns.values
        colors = ["#4CAF50" if v >= 0 else "#F44336" for v in values]

        n_bins = min(50, max(10, len(values) // 5))
        n, bins, patches = ax.hist(values, bins=n_bins, edgecolor="white", linewidth=0.5)

        # Color bars based on sign
        for patch, left_edge in zip(patches, bins[:-1]):
            if left_edge >= 0:
                patch.set_facecolor("#4CAF50")
            else:
                patch.set_facecolor("#F44336")

        ax.axvline(x=0, color="black", linewidth=0.8, linestyle="-")
        ax.axvline(x=values.mean(), color="#2196F3", linewidth=1.0, linestyle="--", label=f"Mean: {values.mean():,.0f}")
        ax.set_title(title)
        ax.set_xlabel("Daily P&L (JPY)")
        ax.set_ylabel("Frequency")
        ax.legend()
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        return fig

    @staticmethod
    def plot_strategy_comparison(strategies_results: dict, metric: str = "roi_pct"):
        """Bar chart comparing strategies on a given metric.

        Args:
            strategies_results: {strategy_name: metrics_dict}.
            metric: Key to compare (default 'roi_pct').

        Returns:
            matplotlib Figure.
        """
        names = list(strategies_results.keys())
        values = [strategies_results[n].get(metric, 0) for n in names]

        fig, ax = plt.subplots(figsize=(8, 5))
        colors = ["#4CAF50" if v >= 100 else "#FF9800" if v >= 80 else "#F44336" for v in values]
        bars = ax.bar(names, values, color=colors, edgecolor="white", linewidth=0.5)

        # Add value labels
        for bar, val in zip(bars, values):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + 0.5,
                f"{val:.1f}",
                ha="center",
                va="bottom",
                fontsize=9,
            )

        metric_labels = {
            "roi_pct": "ROI (%)",
            "hit_rate_pct": "Hit Rate (%)",
            "purchase_rate_pct": "Purchase Rate (%)",
            "daily_win_rate_pct": "Daily Win Rate (%)",
            "sharpe_ratio": "Sharpe Ratio",
            "max_drawdown_pct": "Max Drawdown (%)",
        }
        ylabel = metric_labels.get(metric, metric)
        ax.set_ylabel(ylabel)
        ax.set_title(f"Strategy Comparison: {ylabel}")
        ax.grid(True, alpha=0.3, axis="y")
        fig.tight_layout()
        return fig

    @staticmethod
    def plot_monthly_roi(bets_df: pd.DataFrame, title: str = "Monthly ROI"):
        """Monthly ROI bar chart.

        Args:
            bets_df: DataFrame with columns 'race_date', 'amount', 'payout'.
            title: Chart title.

        Returns:
            matplotlib Figure.
        """
        df = bets_df.copy()
        if "race_date" in df.columns:
            df["month"] = pd.to_datetime(df["race_date"]).dt.to_period("M")
        else:
            df["month"] = pd.to_datetime(df.index).to_period("M")

        monthly = df.groupby("month").agg(
            investment=("amount", "sum"),
            payout=("payout", "sum"),
        )
        monthly["roi"] = monthly["payout"] / monthly["investment"] * 100

        fig, ax = plt.subplots(figsize=(10, 5))
        x_labels = [str(p) for p in monthly.index]
        colors = ["#4CAF50" if r >= 100 else "#F44336" for r in monthly["roi"]]
        bars = ax.bar(x_labels, monthly["roi"].values, color=colors, edgecolor="white")

        ax.axhline(y=100, color="gray", linestyle="--", alpha=0.5, label="Break-even")
        ax.set_title(title)
        ax.set_xlabel("Month")
        ax.set_ylabel("ROI (%)")
        ax.legend()
        ax.grid(True, alpha=0.3, axis="y")
        plt.xticks(rotation=45, ha="right")
        fig.tight_layout()
        return fig

    @staticmethod
    def plot_cumulative_profit(daily_returns: pd.Series, title: str = "Cumulative Profit"):
        """Cumulative sum of daily profits.

        Args:
            daily_returns: pd.Series of daily P&L.
            title: Chart title.

        Returns:
            matplotlib Figure.
        """
        cumulative = daily_returns.cumsum()

        fig, ax = plt.subplots(figsize=(10, 5))
        ax.plot(cumulative.index, cumulative.values, linewidth=1.5, color="#2196F3")
        ax.axhline(y=0, color="gray", linestyle="--", alpha=0.5)
        ax.fill_between(
            cumulative.index,
            0,
            cumulative.values,
            where=cumulative.values >= 0,
            alpha=0.15,
            color="green",
        )
        ax.fill_between(
            cumulative.index,
            0,
            cumulative.values,
            where=cumulative.values < 0,
            alpha=0.15,
            color="red",
        )
        ax.set_title(title)
        ax.set_xlabel("Date")
        ax.set_ylabel("Cumulative Profit (JPY)")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
        ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
        fig.autofmt_xdate()
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        return fig

    @staticmethod
    def save_fig(fig, path: str):
        """Save figure to file."""
        fig.savefig(path, dpi=150, bbox_inches="tight")
        plt.close(fig)

    @staticmethod
    def fig_to_base64(fig) -> str:
        """Convert figure to base64 string for HTML embedding."""
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=120, bbox_inches="tight")
        plt.close(fig)
        buf.seek(0)
        return base64.b64encode(buf.read()).decode("utf-8")
