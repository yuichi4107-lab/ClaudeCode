"""HTML レポート生成モジュール"""

import os
from datetime import datetime

import pandas as pd

from src.reporting.visualizer import Visualizer


class HTMLReportGenerator:
    """Generate self-contained HTML reports with inline CSS and base64 images."""

    def __init__(self, visualizer: Visualizer = None):
        self.viz = visualizer or Visualizer()

    def generate(
        self,
        backtest_result,
        metrics: dict,
        strategy_name: str,
        output_path: str,
    ):
        """Generate a comprehensive HTML report for a single strategy.

        Args:
            backtest_result: BacktestResult object.
            metrics: Metrics dict from MetricsCalculator.
            strategy_name: Strategy display name.
            output_path: File path to save HTML.
        """
        charts = {}

        # Generate charts
        if backtest_result.equity_curve is not None and len(backtest_result.equity_curve) > 0:
            fig = self.viz.plot_equity_curve(
                backtest_result.equity_curve,
                title=f"{strategy_name} - Equity Curve",
            )
            charts["equity_curve"] = self.viz.fig_to_base64(fig)

            fig = self.viz.plot_drawdown(
                backtest_result.equity_curve,
                title=f"{strategy_name} - Drawdown",
            )
            charts["drawdown"] = self.viz.fig_to_base64(fig)

        if backtest_result.daily_returns is not None and len(backtest_result.daily_returns) > 0:
            fig = self.viz.plot_daily_returns(
                backtest_result.daily_returns,
                title=f"{strategy_name} - Daily Returns",
            )
            charts["daily_returns"] = self.viz.fig_to_base64(fig)

            fig = self.viz.plot_cumulative_profit(
                backtest_result.daily_returns,
                title=f"{strategy_name} - Cumulative Profit",
            )
            charts["cumulative_profit"] = self.viz.fig_to_base64(fig)

        # Monthly ROI from bets
        if backtest_result.bets:
            bets_df = pd.DataFrame([
                {
                    "race_date": b.race_date,
                    "amount": b.amount,
                    "payout": b.payout,
                    "bet_type": b.bet_type,
                }
                for b in backtest_result.bets
            ])
            fig = self.viz.plot_monthly_roi(bets_df, title=f"{strategy_name} - Monthly ROI")
            charts["monthly_roi"] = self.viz.fig_to_base64(fig)

        # Target achievement
        targets = self._check_targets(metrics)

        # Bet type breakdown
        bet_breakdown = self._bet_type_breakdown(backtest_result.bets)

        content = {
            "strategy_name": strategy_name,
            "metrics": metrics,
            "charts": charts,
            "targets": targets,
            "bet_breakdown": bet_breakdown,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        html = self._render_html(content)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html)

    def generate_comparison_report(
        self,
        results_dict: dict,
        metrics_dict: dict,
        output_path: str,
    ):
        """Generate comparison report for multiple strategies.

        Args:
            results_dict: {strategy_name: BacktestResult}.
            metrics_dict: {strategy_name: metrics_dict}.
            output_path: File path to save HTML.
        """
        charts = {}

        # Strategy comparison charts
        for metric_key in ["roi_pct", "hit_rate_pct", "daily_win_rate_pct", "sharpe_ratio"]:
            fig = self.viz.plot_strategy_comparison(metrics_dict, metric=metric_key)
            charts[f"comparison_{metric_key}"] = self.viz.fig_to_base64(fig)

        # Equity curves overlay
        equity_curves = {}
        for name, result in results_dict.items():
            if result.equity_curve is not None and len(result.equity_curve) > 0:
                equity_curves[name] = result.equity_curve

        if equity_curves:
            fig = self._plot_equity_overlay(equity_curves)
            charts["equity_overlay"] = self.viz.fig_to_base64(fig)

        content = {
            "metrics_dict": metrics_dict,
            "charts": charts,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        html = self._render_comparison_html(content)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html)

    def _check_targets(self, metrics: dict) -> dict:
        """Check if metrics meet target thresholds."""
        return {
            "roi_150": {
                "target": 150.0,
                "actual": metrics.get("roi_pct", 0.0),
                "pass": metrics.get("roi_pct", 0.0) >= 150.0,
                "label": "ROI >= 150%",
            },
            "purchase_30": {
                "target": 30.0,
                "actual": metrics.get("purchase_rate_pct", 0.0),
                "pass": metrics.get("purchase_rate_pct", 0.0) >= 30.0,
                "label": "Purchase Rate >= 30%",
            },
            "daily_win_50": {
                "target": 50.0,
                "actual": metrics.get("daily_win_rate_pct", 0.0),
                "pass": metrics.get("daily_win_rate_pct", 0.0) >= 50.0,
                "label": "Daily Win Rate >= 50%",
            },
        }

    def _bet_type_breakdown(self, bets: list) -> dict:
        """Calculate per-bet-type statistics."""
        breakdown = {}
        for bet in bets:
            bt = bet.bet_type
            if bt not in breakdown:
                breakdown[bt] = {"count": 0, "investment": 0.0, "payout": 0.0, "hits": 0}
            breakdown[bt]["count"] += 1
            breakdown[bt]["investment"] += bet.amount
            breakdown[bt]["payout"] += bet.payout
            if bet.is_hit:
                breakdown[bt]["hits"] += 1

        for bt, stats in breakdown.items():
            stats["roi_pct"] = (
                stats["payout"] / stats["investment"] * 100
                if stats["investment"] > 0
                else 0.0
            )
            stats["hit_rate_pct"] = (
                stats["hits"] / stats["count"] * 100
                if stats["count"] > 0
                else 0.0
            )
        return breakdown

    def _plot_equity_overlay(self, equity_curves: dict):
        """Plot multiple equity curves on the same chart."""
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates

        fig, ax = plt.subplots(figsize=(10, 5))
        colors = ["#2196F3", "#4CAF50", "#FF9800", "#9C27B0", "#F44336"]

        for i, (name, curve) in enumerate(equity_curves.items()):
            color = colors[i % len(colors)]
            ax.plot(curve.index, curve.values, linewidth=1.5, label=name, color=color)

        ax.set_title("Equity Curves Comparison")
        ax.set_xlabel("Date")
        ax.set_ylabel("Equity (JPY)")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
        ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
        fig.autofmt_xdate()
        ax.legend()
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        return fig

    def _render_html(self, content: dict) -> str:
        """Build single-strategy HTML report."""
        name = content["strategy_name"]
        m = content["metrics"]
        charts = content["charts"]
        targets = content["targets"]
        breakdown = content["bet_breakdown"]
        generated = content["generated_at"]

        # Target achievement rows
        target_rows = ""
        for key, t in targets.items():
            status = "PASS" if t["pass"] else "FAIL"
            status_color = "#4CAF50" if t["pass"] else "#F44336"
            target_rows += f"""
            <tr>
                <td>{t['label']}</td>
                <td style="text-align:right">{t['actual']:.1f}%</td>
                <td style="text-align:right">{t['target']:.0f}%</td>
                <td style="text-align:center;color:{status_color};font-weight:bold">{status}</td>
            </tr>"""

        # Metrics table
        metrics_rows = f"""
        <tr><td>ROI</td><td style="text-align:right">{m.get('roi_pct', 0):.1f}%</td></tr>
        <tr><td>Hit Rate</td><td style="text-align:right">{m.get('hit_rate_pct', 0):.1f}%</td></tr>
        <tr><td>Purchase Rate</td><td style="text-align:right">{m.get('purchase_rate_pct', 0):.1f}%</td></tr>
        <tr><td>Daily Win Rate</td><td style="text-align:right">{m.get('daily_win_rate_pct', 0):.1f}%</td></tr>
        <tr><td>Max Drawdown</td><td style="text-align:right">{m.get('max_drawdown_pct', 0):.1f}%</td></tr>
        <tr><td>Sharpe Ratio</td><td style="text-align:right">{m.get('sharpe_ratio', 0):.2f}</td></tr>
        <tr><td>Profit Factor</td><td style="text-align:right">{m.get('profit_factor', 0):.2f}</td></tr>
        <tr><td>Calmar Ratio</td><td style="text-align:right">{m.get('calmar_ratio', 0):.2f}</td></tr>
        <tr><td>Max Consecutive Loss</td><td style="text-align:right">{m.get('consecutive_loss_max', 0)}</td></tr>
        <tr><td>Total Bets</td><td style="text-align:right">{m.get('total_bets', 0):,}</td></tr>
        <tr><td>Total Investment</td><td style="text-align:right">{m.get('total_investment', 0):,.0f} JPY</td></tr>
        <tr><td>Total Payout</td><td style="text-align:right">{m.get('total_payout', 0):,.0f} JPY</td></tr>
        <tr><td>Net Profit</td><td style="text-align:right">{m.get('net_profit', 0):+,.0f} JPY</td></tr>"""

        # Bet type breakdown rows
        bt_rows = ""
        for bt, stats in sorted(breakdown.items()):
            bt_rows += f"""
            <tr>
                <td>{bt}</td>
                <td style="text-align:right">{stats['count']:,}</td>
                <td style="text-align:right">{stats['investment']:,.0f}</td>
                <td style="text-align:right">{stats['payout']:,.0f}</td>
                <td style="text-align:right">{stats['roi_pct']:.1f}%</td>
                <td style="text-align:right">{stats['hit_rate_pct']:.1f}%</td>
            </tr>"""

        # Chart images
        chart_html = ""
        chart_titles = {
            "equity_curve": "Equity Curve",
            "drawdown": "Drawdown",
            "daily_returns": "Daily Returns Distribution",
            "cumulative_profit": "Cumulative Profit",
            "monthly_roi": "Monthly ROI",
        }
        for key, title in chart_titles.items():
            if key in charts:
                chart_html += f"""
                <div class="chart-container">
                    <img src="data:image/png;base64,{charts[key]}" alt="{title}" />
                </div>"""

        return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{name} - Backtest Report</title>
<style>
{self._css()}
</style>
</head>
<body>
<div class="container">
    <h1>{name} - Backtest Report</h1>
    <p class="generated">Generated: {generated}</p>

    <h2>Target Achievement</h2>
    <table>
        <thead>
            <tr><th>Target</th><th>Actual</th><th>Required</th><th>Status</th></tr>
        </thead>
        <tbody>{target_rows}</tbody>
    </table>

    <h2>Summary Statistics</h2>
    <table>
        <thead><tr><th>Metric</th><th>Value</th></tr></thead>
        <tbody>{metrics_rows}</tbody>
    </table>

    <h2>Bet Type Breakdown</h2>
    <table>
        <thead>
            <tr><th>Type</th><th>Count</th><th>Investment</th><th>Payout</th><th>ROI</th><th>Hit Rate</th></tr>
        </thead>
        <tbody>{bt_rows}</tbody>
    </table>

    <h2>Charts</h2>
    {chart_html}
</div>
</body>
</html>"""

    def _render_comparison_html(self, content: dict) -> str:
        """Build comparison HTML report."""
        metrics_dict = content["metrics_dict"]
        charts = content["charts"]
        generated = content["generated_at"]

        # Comparison table
        strategies = list(metrics_dict.keys())
        metric_keys = [
            ("ROI", "roi_pct", "%"),
            ("Hit Rate", "hit_rate_pct", "%"),
            ("Purchase Rate", "purchase_rate_pct", "%"),
            ("Daily Win Rate", "daily_win_rate_pct", "%"),
            ("Max Drawdown", "max_drawdown_pct", "%"),
            ("Sharpe Ratio", "sharpe_ratio", ""),
            ("Profit Factor", "profit_factor", ""),
            ("Total Bets", "total_bets", ""),
            ("Net Profit", "net_profit", " JPY"),
        ]

        header_cells = "".join(f"<th>{s}</th>" for s in strategies)
        table_rows = ""
        for label, key, suffix in metric_keys:
            cells = ""
            for s in strategies:
                val = metrics_dict[s].get(key, 0)
                if key == "net_profit":
                    cells += f'<td style="text-align:right">{val:+,.0f}{suffix}</td>'
                elif key == "total_bets":
                    cells += f'<td style="text-align:right">{int(val):,}{suffix}</td>'
                elif suffix == "%":
                    cells += f'<td style="text-align:right">{val:.1f}{suffix}</td>'
                else:
                    cells += f'<td style="text-align:right">{val:.2f}{suffix}</td>'
            table_rows += f"<tr><td>{label}</td>{cells}</tr>"

        # Chart images
        chart_html = ""
        for key, b64 in charts.items():
            chart_html += f"""
            <div class="chart-container">
                <img src="data:image/png;base64,{b64}" alt="{key}" />
            </div>"""

        return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Strategy Comparison Report</title>
<style>
{self._css()}
</style>
</head>
<body>
<div class="container">
    <h1>Strategy Comparison Report</h1>
    <p class="generated">Generated: {generated}</p>

    <h2>Side-by-Side Metrics</h2>
    <table>
        <thead><tr><th>Metric</th>{header_cells}</tr></thead>
        <tbody>{table_rows}</tbody>
    </table>

    <h2>Comparison Charts</h2>
    {chart_html}
</div>
</body>
</html>"""

    def _css(self) -> str:
        """Inline CSS for reports."""
        return """
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: #f5f5f5; color: #333; line-height: 1.6;
}
.container { max-width: 1100px; margin: 0 auto; padding: 20px; }
h1 {
    color: #1a237e; border-bottom: 3px solid #1a237e;
    padding-bottom: 10px; margin-bottom: 20px;
}
h2 { color: #283593; margin: 30px 0 15px; }
p.generated { color: #666; font-size: 0.9em; margin-bottom: 20px; }
table {
    width: 100%; border-collapse: collapse; background: #fff;
    box-shadow: 0 1px 3px rgba(0,0,0,0.12); margin-bottom: 20px;
}
th {
    background: #1a237e; color: #fff; padding: 10px 12px;
    text-align: left; font-weight: 600;
}
td { padding: 8px 12px; border-bottom: 1px solid #e0e0e0; }
tr:hover { background: #f5f5f5; }
.chart-container {
    background: #fff; padding: 15px; margin-bottom: 20px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.12); border-radius: 4px;
    text-align: center;
}
.chart-container img { max-width: 100%; height: auto; }
"""
