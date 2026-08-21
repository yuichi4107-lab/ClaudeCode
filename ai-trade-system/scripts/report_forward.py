"""
フォワードテスト結果レポートを生成する。

使い方:
    python scripts/report_forward.py
    python scripts/report_forward.py --start 2026-04-13 --end 2026-05-13
    python scripts/report_forward.py --output results/forward/report_20260413.txt
    python scripts/report_forward.py --log-dir logs/forward --output results/forward/report.txt

出力形式（テキスト）:
    ============================================================
      FX Phase1 フォワードテストレポート
      期間: 2026-04-13 〜 2026-05-13
    ============================================================
    ...
"""

import argparse
import os
import sys

# プロジェクトルートをパスに追加
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_SCRIPT_DIR, ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.forward.log_aggregator import LogAggregator  # noqa: E402


def _pct_str(value: float, decimals: int = 2) -> str:
    """損益率を符号付きの文字列に変換する。"""
    if value > 0:
        return f"+{value:.{decimals}f}%"
    return f"{value:.{decimals}f}%"


def _deviation_str(value: float) -> str:
    """乖離率を符号付きの文字列に変換する。"""
    if value > 0:
        return f"+{value:.1f}%"
    return f"{value:.1f}%"


def build_report(
    aggregated: dict,
    deviation: dict,
    start_date: str,
    end_date: str,
) -> str:
    """
    集計結果からレポートテキストを組み立てる。

    Args:
        aggregated: LogAggregator.aggregate() の返り値
        deviation:  LogAggregator.compare_with_backtest() の返り値
        start_date: 集計開始日（表示用）
        end_date:   集計終了日（表示用）

    Returns:
        レポートテキスト文字列
    """
    SEP = "=" * 60

    # 期間表示
    period_start = aggregated.get("period_start") or start_date or "---"
    period_end = aggregated.get("period_end") or end_date or "---"

    lines = []
    lines.append(SEP)
    lines.append("  FX Phase1 フォワードテストレポート")
    lines.append(f"  期間: {period_start} 〜 {period_end}")
    lines.append(SEP)
    lines.append("")

    # データゼロ件の判定
    total_trades = aggregated.get("total_trades", 0)
    if total_trades == 0:
        lines.append("【データなし】")
        lines.append("  集計期間内にトレードデータが存在しません。")
        lines.append("  フォワードテストを開始し、trades_YYYYMMDD.jsonl が生成されると")
        lines.append("  本レポートに集計結果が表示されます。")
        lines.append("")
        lines.append(SEP)
        return "\n".join(lines)

    # 全体サマリー
    win_rate = aggregated.get("win_rate_pct", 0.0)
    total_pnl = aggregated.get("total_pnl_pct", 0.0)
    pf = aggregated.get("profit_factor", 0.0)
    max_dd = aggregated.get("max_drawdown_pct", 0.0)

    lines.append("【全体サマリー】")
    lines.append(f"  総トレード数   : {total_trades}")
    lines.append(f"  勝率           : {win_rate:.1f}%")
    lines.append(f"  総損益         : {_pct_str(total_pnl)}")
    lines.append(f"  プロフィットファクター: {pf:.2f}")
    lines.append(f"  最大ドローダウン: {max_dd:.2f}%")
    lines.append("")

    # バックテスト乖離分析
    mr_expected = deviation.get("monthly_return_expected", 0.0)
    mr_actual = deviation.get("monthly_return_actual", 0.0)
    mr_dev = deviation.get("monthly_return_deviation_pct", 0.0)
    dd_expected = deviation.get("max_dd_expected", 0.0)
    dd_actual = deviation.get("max_dd_actual", 0.0)
    dd_dev = deviation.get("max_dd_deviation_pct", 0.0)

    lines.append("【バックテスト乖離分析】")
    lines.append(
        f"  月利（期待/実績/乖離）: {mr_expected:.2f}% / "
        f"{_pct_str(mr_actual)} / {_deviation_str(mr_dev)}"
    )
    lines.append(
        f"  MaxDD（期待/実績/乖離）: {dd_expected:.2f}% / "
        f"{dd_actual:.2f}% / {_deviation_str(dd_dev)}"
    )
    lines.append("")

    # 戦略別内訳
    by_strategy = aggregated.get("by_strategy", {})
    lines.append("【戦略別内訳】")

    strategy_display = {
        "mtf_confluence":    "mtf_confluence ",
        "rsi_divergence":    "rsi_divergence ",
        "bb_reversion_USDJPY": "bb_rev_USDJPY  ",
        "bb_reversion_EURJPY": "bb_rev_EURJPY  ",
    }

    for key, display_name in strategy_display.items():
        s = by_strategy.get(key, {})
        n = s.get("total_trades", 0)
        wr = s.get("win_rate_pct", 0.0)
        pnl = s.get("total_pnl_pct", 0.0)
        pnl_str = _pct_str(pnl)
        lines.append(
            f"  {display_name}: {n:3d} trades, WR {wr:5.1f}%, PnL {pnl_str}"
        )
    lines.append("")

    # サーキットブレーカー発動
    cb = aggregated.get("cb_triggers", {})
    lines.append("【サーキットブレーカー発動】")
    lines.append(f"  CB1（連敗5回）    : {cb.get('cb1', 0)}回")
    lines.append(f"  CB2（月次DD-10%） : {cb.get('cb2', 0)}回")
    lines.append(f"  CB3（累積DD-25%） : {cb.get('cb3', 0)}回")
    lines.append(f"  CB4（前月マイナス）: {cb.get('cb4', 0)}回")
    lines.append("")

    # 日次損益推移
    daily_pnl = aggregated.get("daily_pnl", [])
    if daily_pnl:
        lines.append("【日次損益推移】")
        cumulative = 0.0
        for entry in daily_pnl:
            d = entry.get("date", "")
            pnl_d = entry.get("pnl_pct", 0.0)
            cumulative += pnl_d
            lines.append(
                f"  {d}  {_pct_str(pnl_d, 3):>10s}  (累計: {_pct_str(cumulative, 3)})"
            )
        lines.append("")

    lines.append(SEP)
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="FX Phase1 フォワードテスト結果レポートを生成する。"
    )
    parser.add_argument(
        "--start",
        metavar="YYYY-MM-DD",
        default=None,
        help="集計開始日（例: 2026-04-13）",
    )
    parser.add_argument(
        "--end",
        metavar="YYYY-MM-DD",
        default=None,
        help="集計終了日（例: 2026-05-13）",
    )
    parser.add_argument(
        "--output",
        metavar="PATH",
        default=None,
        help="レポート出力先ファイルパス（省略時は標準出力）",
    )
    parser.add_argument(
        "--log-dir",
        metavar="DIR",
        default="logs/forward",
        help="トレードログディレクトリ（デフォルト: logs/forward）",
    )

    args = parser.parse_args()

    # ログディレクトリの自動作成
    log_dir = args.log_dir
    if not os.path.isabs(log_dir):
        log_dir = os.path.join(_PROJECT_ROOT, log_dir)
    os.makedirs(log_dir, exist_ok=True)

    # 集計実行
    aggregator = LogAggregator(log_dir=log_dir)
    trades = aggregator.load_trades(start_date=args.start, end_date=args.end)
    aggregated = aggregator.aggregate(trades)
    deviation = aggregator.compare_with_backtest(aggregated)

    report = build_report(
        aggregated=aggregated,
        deviation=deviation,
        start_date=args.start or "",
        end_date=args.end or "",
    )

    # 出力先の処理
    if args.output:
        output_path = args.output
        if not os.path.isabs(output_path):
            output_path = os.path.join(_PROJECT_ROOT, output_path)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"レポートを保存しました: {output_path}")
    else:
        print(report)


if __name__ == "__main__":
    main()
