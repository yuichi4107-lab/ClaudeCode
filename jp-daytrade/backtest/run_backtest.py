"""
バックテスト CLI。

全期間バックテストを 1 コマンドで実行し、レポート（Markdown + CSV）を生成する。

使い方:
    python -m jp-daytrade.backtest.run_backtest
    # または
    python jp-daytrade/backtest/run_backtest.py

環境変数:
    JP_DAYTRADE_DATA_DIR  : データベースのディレクトリパス（デフォルト: C:/dev/jp-daytrade-data）
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# パッケージルートを sys.path に追加（直接実行時の対応）
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from jp_daytrade.strategy.screener import run_screening_pipeline
from jp_daytrade.backtest.engine import run_backtest, BacktestResult, Trade

# ---------------------------------------------------------------------------
# ログ設定
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 出力パス
# ---------------------------------------------------------------------------
_RESULTS_DIR = _HERE / "results"
_REPORT_PATH = _RESULTS_DIR / "bt_report_v1.md"
_TRADES_PATH = _RESULTS_DIR / "trades_v1.csv"


# ---------------------------------------------------------------------------
# 取引ログ → CSV
# ---------------------------------------------------------------------------

def trades_to_dataframe(trades: list[Trade]) -> pd.DataFrame:
    """取引リストを DataFrame に変換する。"""
    records = []
    cumulative_pnl = 0.0
    for t in trades:
        cumulative_pnl += t.pnl_abs
        records.append({
            "date": t.date,
            "code": t.code,
            "open": t.open_price,
            "entry_price": round(t.entry_price, 2),
            "high": t.high,
            "low": t.low,
            "close": t.close_price_day,
            "sl_price": round(t.sl_price, 2),
            "tp1_price": round(t.tp1_price, 2),
            "tp2_price": round(t.tp2_price, 2),
            "exit_reason": t.exit_reason,
            "exit_price": round(t.exit_price_full, 2),
            "pnl_pct": round(t.pnl_pct * 100, 4),   # %表示
            "pnl_abs": round(t.pnl_abs, 0),
            "cumulative_pnl": round(cumulative_pnl, 0),
            "invested": round(t.invested, 0),
            "shares": round(t.shares, 2),
            "bonus_score": t.bonus_score,
            "is_yori_ten": t.is_yori_ten,
        })
    return pd.DataFrame(records)


# ---------------------------------------------------------------------------
# 月次 PnL 集計
# ---------------------------------------------------------------------------

def compute_monthly_pnl(df_trades: pd.DataFrame) -> pd.DataFrame:
    """月次 PnL を集計する。"""
    df = df_trades.copy()
    df["month"] = pd.to_datetime(df["date"]).dt.to_period("M")
    monthly = (
        df.groupby("month")["pnl_abs"]
        .agg(["sum", "count"])
        .rename(columns={"sum": "pnl_abs", "count": "trades"})
    )
    monthly["pnl_abs"] = monthly["pnl_abs"].round(0)
    return monthly


# ---------------------------------------------------------------------------
# Markdown レポート生成
# ---------------------------------------------------------------------------

def generate_report(result: BacktestResult, df_trades: pd.DataFrame, monthly: pd.DataFrame) -> str:
    """
    バックテスト結果を Markdown 形式で生成する。

    Parameters
    ----------
    result : BacktestResult
    df_trades : pd.DataFrame
    monthly : pd.DataFrame

    Returns
    -------
    str
        Markdown テキスト
    """
    from jp_daytrade.strategy.config import BACKTEST_CONFIG, SCREENING_CONFIG

    bc = BACKTEST_CONFIG
    sc = SCREENING_CONFIG

    # 合格基準チェック
    criteria = {
        "勝率 ≥ 55%": result.win_rate >= 0.55,
        "PF ≥ 1.3": result.profit_factor >= 1.3,
        "シャープ ≥ 0.8": result.sharpe_ratio >= 0.8,
        "最大DD ≤ 20%": result.max_drawdown >= -0.20,
        "寄り天発生率 ≤ 30%": result.yori_ten_rate <= 0.30,
    }
    all_pass = all(criteria.values())

    # Exit reason 集計
    exit_counts = df_trades["exit_reason"].value_counts().to_dict() if not df_trades.empty else {}

    lines = [
        "# JP-DAYTRADE-v1 バックテストレポート",
        "",
        f"- **生成日時**: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- **データ期間**: {df_trades['date'].min() if not df_trades.empty else 'N/A'} 〜 {df_trades['date'].max() if not df_trades.empty else 'N/A'}",
        f"- **バックテスト設定**: max_positions={bc['max_positions']}, slippage={bc['slippage']*100:.1f}%, commission={bc['commission']:.0f}円",
        f"- **スリッページ**: {bc['slippage']*100:.1f}%（エントリー・エグジット両方）",
        f"- **ライブ専用フィルター**: F6（寄り前売買比率）・F7（板厚み）は live_only=True のためバックテストでスキップ",
        f"- **F2（時価総額）**: データ未提供のためスキップ（将来対応）",
        f"- **初期資金**: {bc['initial_capital']:,.0f}円",
        "",
        "## パフォーマンス指標",
        "",
        f"| 指標 | 値 | 合格基準 | 判定 |",
        f"|------|----|---------|------|",
        f"| 総取引数 | {result.total_trades} 件 | - | - |",
        f"| 勝率 | {result.win_rate*100:.2f}% | ≥ 55% | {'✓' if criteria['勝率 ≥ 55%'] else '✗'} |",
        f"| プロフィットファクター | {result.profit_factor:.3f} | ≥ 1.3 | {'✓' if criteria['PF ≥ 1.3'] else '✗'} |",
        f"| シャープレシオ（年換算） | {result.sharpe_ratio:.3f} | ≥ 0.8 | {'✓' if criteria['シャープ ≥ 0.8'] else '✗'} |",
        f"| 最大ドローダウン | {result.max_drawdown*100:.2f}% | ≤ -20% | {'✓' if criteria['最大DD ≤ 20%'] else '✗'} |",
        f"| 期待値（1取引あたり） | {result.expected_value*100:.4f}% | - | - |",
        f"| 寄り天発生率 | {result.yori_ten_rate*100:.2f}% | ≤ 30% | {'✓' if criteria['寄り天発生率 ≤ 30%'] else '✗'} |",
        f"| 最終資産 | {result.final_capital:,.0f}円 | - | - |",
        f"| 総収益 | {result.final_capital - 1_000_000:+,.0f}円 | - | - |",
        "",
        f"**総合判定**: {'✓ 合格（全基準クリア）' if all_pass else '✗ 不合格（下記原因分析を参照）'}",
        "",
    ]

    # エグジット理由内訳
    lines += [
        "## エグジット理由内訳",
        "",
        "| 理由 | 件数 | 割合 |",
        "|------|------|------|",
    ]
    for reason, cnt in sorted(exit_counts.items(), key=lambda x: -x[1]):
        ratio = cnt / result.total_trades * 100 if result.total_trades > 0 else 0
        lines.append(f"| {reason} | {cnt} | {ratio:.1f}% |")
    lines.append("")

    # 月次 PnL
    lines += [
        "## 月次 PnL",
        "",
        "| 月 | PnL（円） | 取引数 |",
        "|----|-----------|--------|",
    ]
    for period, row in monthly.iterrows():
        lines.append(f"| {period} | {row['pnl_abs']:+,.0f} | {int(row['trades'])} |")
    lines.append("")

    # スクリーニング設定サマリー
    lines += [
        "## スクリーニング設定",
        "",
        f"| フィルター | 設定値 | 状態 |",
        f"|-----------|--------|------|",
        f"| F1: 株価上限 | ≤ {sc['max_price']:,}円 | 有効 |",
        f"| F2: 時価総額 | {sc['market_cap_min_billion']}〜{sc['market_cap_max_billion']}億円 | **スキップ（データ未整備）** |",
        f"| F3: 日中値幅率 | ≥ {sc['intraday_range_min']*100:.0f}%（{sc['intraday_range_days']}日平均） | 有効 |",
        f"| F4: 前日出来高 | ≥ {sc['volume_min']:,}株 | 有効 |",
        f"| F5 (proxy): GAP率 | ≥ +{sc['gap_rate_min']*100:.0f}%（Openで代用） | 有効 |",
        f"| F6: 寄り前売買比率 | ≤ 0.8 | **live_only（スキップ）** |",
        f"| F7: 板厚み | ≥ 10,000株 | **live_only（スキップ）** |",
        f"| 加点1: 適時開示 | - | **スキップ（データ未整備）** |",
        f"| 加点3: 出来高比率 | ≥ {sc['volume_ratio_vs_week_ago_min']*100:.0f}%（前週同日比） | 有効 |",
        "",
    ]

    # 不合格時の原因分析
    if not all_pass:
        lines += [
            "## 不合格項目の原因分析",
            "",
        ]
        if not criteria["勝率 ≥ 55%"]:
            lines.append(f"- **勝率 {result.win_rate*100:.2f}% < 55%**: "
                         "GAP+3% プロキシフィルターのみでは上昇継続の確度が低い可能性。"
                         "F6（寄り前売買比率）をライブで追加することで改善が期待される。")
        if not criteria["PF ≥ 1.3"]:
            lines.append(f"- **PF {result.profit_factor:.3f} < 1.3**: "
                         "損益比（TP+5/10% vs SL-2%）は有利だが、勝率が不足している可能性。")
        if not criteria["シャープ ≥ 0.8"]:
            lines.append(f"- **シャープ {result.sharpe_ratio:.3f} < 0.8**: "
                         "日次収益の変動が大きい。同時保有数を増やすと分散効果で改善する可能性。")
        if not criteria["最大DD ≤ 20%"]:
            lines.append(f"- **最大DD {result.max_drawdown*100:.2f}% > 20%**: "
                         "ポジションサイズか SL 幅を見直す必要がある。")
        if not criteria["寄り天発生率 ≤ 30%"]:
            lines.append(f"- **寄り天発生率 {result.yori_ten_rate*100:.2f}% > 30%**: "
                         "GAP アップ直後に高値をつけて反転するパターンが多い。"
                         "F6（寄り前売買比率）や F7（板厚み）をライブで適用することで改善が期待される。")
        lines.append("")

    lines += [
        "## データ制約・制限事項",
        "",
        "- J-Quants Free プランは**日足のみ**提供。8:59 時点の買気配・板は利用不可。",
        "- F5（GAP率）は本来「8:59 買気配 / 前日終値」だが、日足では寄り付き価格（Open）で代用している。",
        "  この代用により、ライブでは GAP を事前（寄り前）に確認できないケースを除外できないため、",
        "  実戦パフォーマンスはバックテスト値より低くなる可能性がある。",
        "- TP/SL 到達タイミングの先後関係は日足では不明。**保守的評価（Low→High 順）** を採用。",
        "  実戦では損切の方が先でないケースもあるため、バックテスト値は過悲観の可能性がある。",
        "",
        "## 再現方法",
        "",
        "```bash",
        "# 環境変数設定（デフォルト: C:/dev/jp-daytrade-data）",
        "export JP_DAYTRADE_DATA_DIR=C:/dev/jp-daytrade-data",
        "# バックテスト実行",
        "cd <repo_root>",
        "python jp-daytrade/backtest/run_backtest.py",
        "```",
        "",
        "同一入力（DB ファイル）に対して常に同一出力（CSV）を生成する（確定的処理）。",
    ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------

def main() -> None:
    """バックテストを実行してレポートを生成する。"""
    _RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    logger.info("=== JP-DAYTRADE-v1 バックテスト開始 ===")

    # スクリーニングパイプライン
    logger.info("Step 1: スクリーニングパイプライン実行中...")
    prices_all, trading_days, eligible_codes = run_screening_pipeline()

    logger.info("Step 2: バックテスト実行中（%d 営業日）...", len(trading_days))
    result = run_backtest(
        prices_all=prices_all,
        trading_days=trading_days,
        eligible_codes=eligible_codes,
    )

    logger.info("Step 3: 結果を出力中...")

    # CSV 出力
    df_trades = trades_to_dataframe(result.trades)
    df_trades.to_csv(_TRADES_PATH, index=False, encoding="utf-8-sig")
    logger.info("trades CSV: %s (%d rows)", _TRADES_PATH, len(df_trades))

    # 月次集計
    monthly = compute_monthly_pnl(df_trades) if not df_trades.empty else pd.DataFrame()

    # Markdown レポート
    report_md = generate_report(result, df_trades, monthly)
    _REPORT_PATH.write_text(report_md, encoding="utf-8")
    logger.info("report MD: %s", _REPORT_PATH)

    # サマリー出力
    print("\n" + "=" * 60)
    print("JP-DAYTRADE-v1 バックテスト完了")
    print("=" * 60)
    print(f"総取引数: {result.total_trades}")
    print(f"勝率    : {result.win_rate*100:.2f}%  (基準: ≥55%)")
    print(f"PF      : {result.profit_factor:.3f}  (基準: ≥1.3)")
    print(f"シャープ: {result.sharpe_ratio:.3f}  (基準: ≥0.8)")
    print(f"最大DD  : {result.max_drawdown*100:.2f}%  (基準: ≤-20%)")
    print(f"寄り天率: {result.yori_ten_rate*100:.2f}%  (基準: ≤30%)")
    print(f"最終資産: {result.final_capital:,.0f}円")
    print(f"\nレポート: {_REPORT_PATH}")
    print(f"取引CSV : {_TRADES_PATH}")
    print("=" * 60)


if __name__ == "__main__":
    main()
