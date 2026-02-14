"""レポート生成"""

import json
import logging
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from config.settings import EXPORT_DIR

logger = logging.getLogger(__name__)


class ReportGenerator:
    """Win5予想・バックテストのレポートを生成する"""

    def __init__(self, output_dir: str | Path | None = None):
        self.output_dir = Path(output_dir) if output_dir else EXPORT_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate_prediction_report(
        self,
        target_date: date,
        predictions: dict[str, pd.DataFrame],
        ticket_info: dict | None = None,
        ev_info: dict | None = None,
    ) -> str:
        """予想レポートを生成する"""
        lines = []
        lines.append("=" * 60)
        lines.append(f"  Win5 予想レポート: {target_date}")
        lines.append(f"  生成日時: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        lines.append("=" * 60)
        lines.append("")

        for i, (race_id, pred_df) in enumerate(predictions.items(), 1):
            lines.append(f"■ Race {i}: {race_id}")
            lines.append("-" * 40)

            if pred_df.empty:
                lines.append("  (予測なし)")
                lines.append("")
                continue

            for _, row in pred_df.head(5).iterrows():
                prob = row.get("calibrated_prob", 0)
                name = row.get("horse_name", "?")
                num = row.get("horse_number", 0)
                rank = row.get("rank", 0)
                lines.append(
                    f"  {rank:2d}位: [{num:2d}] {name:<12s}  "
                    f"予測勝率: {prob:.1%}"
                )
            lines.append("")

        if ticket_info:
            lines.append("■ 推奨買い目")
            lines.append("-" * 40)
            lines.append(f"  組合せ数: {ticket_info.get('num_combinations', '?')}")
            lines.append(f"  購入金額: ¥{ticket_info.get('total_cost', 0):,}")
            lines.append(f"  的中確率: {ticket_info.get('hit_probability', 0):.4%}")
            lines.append("")

        if ev_info:
            lines.append("■ 期待値分析")
            lines.append("-" * 40)
            lines.append(f"  推定配当: ¥{ev_info.get('estimated_payout', 0):,.0f}")
            lines.append(f"  期待値:   ¥{ev_info.get('expected_value', 0):,.0f}")
            lines.append(f"  ROI:      {ev_info.get('roi_percent', 0):.1f}%")
            lines.append("")

        lines.append("=" * 60)
        lines.append("※ 本レポートは統計モデルに基づく参考情報です。")
        lines.append("  購入はご自身の判断と責任で行ってください。")
        lines.append("=" * 60)

        report_text = "\n".join(lines)

        # ファイル保存
        filename = f"prediction_{target_date.strftime('%Y%m%d')}.txt"
        path = self.output_dir / filename
        path.write_text(report_text, encoding="utf-8")
        logger.info("Report saved: %s", path)

        return report_text

    def generate_backtest_report(
        self,
        backtest_df: pd.DataFrame,
        roi_info: dict,
        drawdown_info: dict,
        monthly_df: pd.DataFrame | None = None,
    ) -> str:
        """バックテストレポートを生成する"""
        lines = []
        lines.append("=" * 60)
        lines.append("  Win5 バックテストレポート")
        lines.append(f"  生成日時: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        lines.append("=" * 60)
        lines.append("")

        lines.append("■ 全体サマリー")
        lines.append("-" * 40)
        lines.append(f"  イベント数: {len(backtest_df)}")
        lines.append(f"  的中数:     {int(backtest_df['is_hit'].sum())}")
        lines.append(f"  的中率:     {backtest_df['is_hit'].mean():.1%}")
        lines.append(f"  総投資:     ¥{roi_info['total_cost']:,.0f}")
        lines.append(f"  総配当:     ¥{roi_info['total_payout']:,.0f}")
        lines.append(f"  損益:       ¥{roi_info['profit']:,.0f}")
        lines.append(f"  回収率:     {roi_info['roi']:.1f}%")
        lines.append("")

        lines.append("■ リスク分析")
        lines.append("-" * 40)
        lines.append(f"  最大DD:     ¥{drawdown_info['max_drawdown']:,.0f}")
        lines.append(f"  最大DD(%): {drawdown_info['max_drawdown_pct']:.1f}%")
        lines.append(f"  最大連敗:   {drawdown_info['max_consecutive_losses']}回")
        lines.append("")

        if monthly_df is not None and not monthly_df.empty:
            lines.append("■ 月別成績")
            lines.append("-" * 40)
            for _, row in monthly_df.iterrows():
                lines.append(
                    f"  {row['month']}: "
                    f"投資¥{row['total_cost']:,.0f} → "
                    f"配当¥{row['total_payout']:,.0f} "
                    f"(ROI: {row['roi']:.0f}%)"
                )
            lines.append("")

        report_text = "\n".join(lines)

        path = self.output_dir / "backtest_report.txt"
        path.write_text(report_text, encoding="utf-8")
        logger.info("Backtest report saved: %s", path)

        return report_text
