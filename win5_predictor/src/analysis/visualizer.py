"""可視化モジュール"""

import logging
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# 日本語フォント設定
plt.rcParams["font.family"] = "sans-serif"
plt.rcParams["font.sans-serif"] = [
    "MS Gothic", "Meiryo", "Yu Gothic", "Hiragino Sans",
    "IPAexGothic", "DejaVu Sans",
]
plt.rcParams["axes.unicode_minus"] = False


class Visualizer:
    """グラフ描画ユーティリティ"""

    def __init__(self, output_dir: str | Path | None = None):
        from config.settings import EXPORT_DIR
        self.output_dir = Path(output_dir) if output_dir else EXPORT_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def plot_cumulative_profit(self, cum_df: pd.DataFrame, save: bool = True) -> plt.Figure:
        """累計損益のグラフ"""
        fig, ax = plt.subplots(figsize=(12, 6))
        ax.plot(cum_df["event_date"], cum_df["cumulative_profit"], "b-", linewidth=1.5)
        ax.axhline(y=0, color="r", linestyle="--", alpha=0.5)
        ax.fill_between(
            cum_df["event_date"],
            cum_df["cumulative_profit"],
            0,
            where=cum_df["cumulative_profit"] >= 0,
            alpha=0.3,
            color="green",
        )
        ax.fill_between(
            cum_df["event_date"],
            cum_df["cumulative_profit"],
            0,
            where=cum_df["cumulative_profit"] < 0,
            alpha=0.3,
            color="red",
        )
        ax.set_title("Win5 Cumulative Profit")
        ax.set_xlabel("Date")
        ax.set_ylabel("Profit (JPY)")
        plt.xticks(rotation=45)
        plt.tight_layout()

        if save:
            path = self.output_dir / "cumulative_profit.png"
            fig.savefig(path, dpi=150)
            logger.info("Saved: %s", path)

        return fig

    def plot_monthly_roi(self, monthly_df: pd.DataFrame, save: bool = True) -> plt.Figure:
        """月別ROIのグラフ"""
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 10))

        colors = ["green" if p >= 0 else "red" for p in monthly_df["profit"]]
        ax1.bar(monthly_df["month"], monthly_df["profit"], color=colors, alpha=0.7)
        ax1.axhline(y=0, color="black", linestyle="-", alpha=0.3)
        ax1.set_title("Monthly Profit")
        ax1.set_ylabel("Profit (JPY)")
        plt.setp(ax1.xaxis.get_majorticklabels(), rotation=45)

        ax2.plot(monthly_df["month"], monthly_df["roi"], "bo-", markersize=4)
        ax2.axhline(y=100, color="r", linestyle="--", alpha=0.5, label="Break-even")
        ax2.set_title("Monthly ROI (%)")
        ax2.set_ylabel("ROI (%)")
        ax2.legend()
        plt.setp(ax2.xaxis.get_majorticklabels(), rotation=45)

        plt.tight_layout()

        if save:
            path = self.output_dir / "monthly_roi.png"
            fig.savefig(path, dpi=150)
            logger.info("Saved: %s", path)

        return fig

    def plot_feature_importance(
        self, importance_df: pd.DataFrame, top_n: int = 20, save: bool = True
    ) -> plt.Figure:
        """特徴量重要度のグラフ"""
        df = importance_df.head(top_n).iloc[::-1]
        fig, ax = plt.subplots(figsize=(10, 8))
        ax.barh(df["feature"], df["importance"], color="steelblue")
        ax.set_title(f"Top {top_n} Feature Importance")
        ax.set_xlabel("Importance")
        plt.tight_layout()

        if save:
            path = self.output_dir / "feature_importance.png"
            fig.savefig(path, dpi=150)
            logger.info("Saved: %s", path)

        return fig

    def plot_calibration(self, cal_df: pd.DataFrame, save: bool = True) -> plt.Figure:
        """キャリブレーションプロット"""
        fig, ax = plt.subplots(figsize=(8, 8))
        ax.plot([0, 1], [0, 1], "k--", alpha=0.5, label="Perfect calibration")
        ax.scatter(
            cal_df["mean_predicted"],
            cal_df["mean_actual"],
            s=cal_df["count"],
            alpha=0.7,
            label="Model",
        )
        ax.set_title("Calibration Plot")
        ax.set_xlabel("Mean Predicted Probability")
        ax.set_ylabel("Mean Actual Probability")
        ax.legend()
        ax.set_xlim(0, max(0.3, cal_df["mean_predicted"].max() * 1.1))
        ax.set_ylim(0, max(0.3, cal_df["mean_actual"].max() * 1.1))
        plt.tight_layout()

        if save:
            path = self.output_dir / "calibration.png"
            fig.savefig(path, dpi=150)
            logger.info("Saved: %s", path)

        return fig

    def plot_prediction_distribution(
        self, pred_df: pd.DataFrame, save: bool = True
    ) -> plt.Figure:
        """予測確率の分布"""
        fig, ax = plt.subplots(figsize=(10, 6))
        if "calibrated_prob" in pred_df.columns:
            ax.hist(pred_df["calibrated_prob"], bins=50, alpha=0.7, color="steelblue")
        ax.set_title("Prediction Probability Distribution")
        ax.set_xlabel("Predicted Win Probability")
        ax.set_ylabel("Count")
        plt.tight_layout()

        if save:
            path = self.output_dir / "pred_distribution.png"
            fig.savefig(path, dpi=150)
            logger.info("Saved: %s", path)

        return fig
