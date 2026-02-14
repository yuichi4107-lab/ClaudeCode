"""回収率計算"""

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class ROICalculator:
    """回収率・収支の分析"""

    def __init__(self, backtest_results: pd.DataFrame):
        self.df = backtest_results

    def overall_roi(self) -> dict[str, float]:
        """全体の回収率を計算"""
        if self.df.empty:
            return {"roi": 0.0, "total_cost": 0.0, "total_payout": 0.0, "profit": 0.0}

        total_cost = float(self.df["total_cost"].sum())
        total_payout = float(self.df["actual_payout"].sum())
        profit = total_payout - total_cost
        roi = (total_payout / total_cost) * 100 if total_cost > 0 else 0.0

        return {
            "roi": roi,
            "total_cost": total_cost,
            "total_payout": total_payout,
            "profit": profit,
        }

    def monthly_roi(self) -> pd.DataFrame:
        """月別の回収率を計算"""
        if self.df.empty:
            return pd.DataFrame()

        df = self.df.copy()
        df["month"] = pd.to_datetime(df["event_date"]).dt.to_period("M").astype(str)

        monthly = df.groupby("month").agg(
            events=("event_id", "count"),
            hits=("is_hit", "sum"),
            total_cost=("total_cost", "sum"),
            total_payout=("actual_payout", "sum"),
        ).reset_index()

        monthly["profit"] = monthly["total_payout"] - monthly["total_cost"]
        monthly["roi"] = (
            monthly["total_payout"] / monthly["total_cost"] * 100
        ).fillna(0)
        monthly["hit_rate"] = (monthly["hits"] / monthly["events"] * 100).fillna(0)

        return monthly

    def cumulative_profit(self) -> pd.DataFrame:
        """累計損益の推移"""
        if self.df.empty:
            return pd.DataFrame()

        df = self.df.sort_values("event_date").copy()
        df["profit"] = df["actual_payout"] - df["total_cost"]
        df["cumulative_profit"] = df["profit"].cumsum()
        df["cumulative_cost"] = df["total_cost"].cumsum()
        df["cumulative_payout"] = df["actual_payout"].cumsum()
        df["cumulative_roi"] = (
            df["cumulative_payout"] / df["cumulative_cost"] * 100
        ).fillna(0)

        return df[
            ["event_date", "profit", "cumulative_profit", "cumulative_roi"]
        ]

    def drawdown_analysis(self) -> dict[str, float]:
        """最大ドローダウン分析"""
        cum = self.cumulative_profit()
        if cum.empty:
            return {"max_drawdown": 0.0, "max_drawdown_pct": 0.0, "max_consecutive_losses": 0}

        peak = cum["cumulative_profit"].cummax()
        drawdown = cum["cumulative_profit"] - peak

        # 連続非的中
        if "is_hit" in self.df.columns:
            streaks = []
            current = 0
            for hit in self.df.sort_values("event_date")["is_hit"]:
                if not hit:
                    current += 1
                else:
                    streaks.append(current)
                    current = 0
            streaks.append(current)
            max_loss_streak = max(streaks) if streaks else 0
        else:
            max_loss_streak = 0

        total_cost = float(self.df["total_cost"].sum())
        return {
            "max_drawdown": float(drawdown.min()),
            "max_drawdown_pct": float(drawdown.min() / total_cost * 100) if total_cost > 0 else 0.0,
            "max_consecutive_losses": max_loss_streak,
        }
