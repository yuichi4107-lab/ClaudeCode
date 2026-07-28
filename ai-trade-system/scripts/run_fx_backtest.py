"""
工程5: FX バックテスト実行スクリプト（MA+RSI ルールベース）

strategy_config.json の USD-JPY 戦略を読み込み、
取得済みの OHLCV データに対してバックテストを実行する。

戦略:
  1. double_bottom: MA トレンドフィルター + ダブルボトム検出（価格パターンで近似）
  2. rsi_oversold_bounce: RSI 30 以下でのリバウンド

注意:
  - 既存の runner.py（Gemini チャート画像判定）は使用しない
  - FX 向けに軽量なルールベース実装
  - 既存 BTC/JPY システムへの影響なし（共有ファイルは変更しない）

実行方法:
    python scripts/run_fx_backtest.py
    python scripts/run_fx_backtest.py --symbol "USD/JPY" --strategy rsi_oversold_bounce

出力先:
    results/fx_backtest_USDJPY_1year_YYYYMMDD_HHMMSS/
        result.json
    data/fx/backtest_report_USDJPY_1year.md (サマリー)
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime

# パス設定
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

STRATEGY_CONFIG_PATH = os.path.join(PROJECT_ROOT, "src", "backtest", "strategy_config.json")
OHLCV_DIR = os.path.join(PROJECT_ROOT, "data", "fx", "ohlcv")
RESULTS_DIR = os.path.join(PROJECT_ROOT, "results")
REPORT_DIR = os.path.join(PROJECT_ROOT, "data", "fx")


# ─── インジケーター計算 ───

def calc_sma(closes: list, period: int) -> list:
    """単純移動平均（SMA）を計算する。"""
    sma = []
    for i in range(len(closes)):
        if i < period - 1:
            sma.append(None)
        else:
            sma.append(sum(closes[i - period + 1:i + 1]) / period)
    return sma


def calc_rsi(closes: list, period: int = 14) -> list:
    """RSI（Relative Strength Index）を計算する。"""
    rsi = [None] * period
    gains = []
    losses = []

    for i in range(1, period + 1):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    for i in range(period + 1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gain = max(diff, 0)
        loss = max(-diff, 0)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period

        if avg_loss == 0:
            rsi.append(100.0)
        else:
            rs = avg_gain / avg_loss
            rsi.append(100.0 - 100.0 / (1 + rs))

    return rsi


# ─── シグナル検出 ───

def detect_rsi_oversold_bounce(candles: list, rsi_period: int = 14, rsi_threshold: float = 30.0) -> list:
    """
    RSI が rsi_threshold 以下から回復したタイミングでエントリーシグナルを生成する。

    条件: RSI[i-1] <= threshold かつ RSI[i] > threshold

    Returns:
        list of int: シグナル発生インデックス
    """
    closes = [c["close"] for c in candles]
    rsi = calc_rsi(closes, period=rsi_period)
    signals = []

    for i in range(1, len(rsi)):
        if rsi[i - 1] is None or rsi[i] is None:
            continue
        if rsi[i - 1] <= rsi_threshold and rsi[i] > rsi_threshold:
            signals.append(i)

    logger.info(f"RSI Oversold Bounce シグナル: {len(signals)}件")
    return signals


def detect_double_bottom_rule_based(
    candles: list,
    window: int = 20,
    sma_fast: int = 50,
    sma_slow: int = 200,
    trend_filter: bool = True,
) -> list:
    """
    ルールベースのダブルボトム近似検出。

    条件:
    1. 直近 window 本の中で、最安値が2回現れる（ダブルボトム形状）
    2. trend_filter=True の場合、SMA50 > SMA200 のみ（上昇トレンド）でエントリー

    Returns:
        list of int: シグナル発生インデックス
    """
    closes = [c["close"] for c in candles]
    lows = [c["low"] for c in candles]

    sma_f = calc_sma(closes, sma_fast)
    sma_s = calc_sma(closes, sma_slow)
    signals = []

    for i in range(window, len(candles)):
        # トレンドフィルター: SMA50 > SMA200
        if trend_filter:
            if sma_f[i] is None or sma_s[i] is None:
                continue
            if sma_f[i] <= sma_s[i]:
                continue

        # 直近 window 本のローを取得
        window_lows = lows[i - window:i]
        min_low = min(window_lows)

        # 最安値が2回現れているか確認（ダブルボトム近似）
        idx_first = window_lows.index(min_low)
        remaining = window_lows[idx_first + 1:]
        if not remaining:
            continue

        # 残りの部分で類似の安値（±0.5%以内）があるか
        tolerance = min_low * 0.005
        double_count = sum(1 for v in remaining if abs(v - min_low) <= tolerance)

        if double_count >= 1:
            # 現在の価格が安値から少し反発しているか
            if closes[i] > min_low * 1.001:
                signals.append(i)

    logger.info(f"Double Bottom シグナル: {len(signals)}件")
    return signals


# ─── バックテスト計算 ───

def run_strategy_backtest(
    candles: list,
    signals: list,
    hold_bars: int,
    take_profit: float = None,
    stop_loss: float = None,
    fee_rate: float = 0.0001,  # FX 手数料は低め（スプレッドのみ）
    direction: str = "long",
) -> list:
    """
    シグナルリストに基づいてトレードを実行し、損益を計算する。

    Args:
        candles: OHLCV データ
        signals: エントリーインデックスのリスト
        hold_bars: 保有期間（バー数）
        take_profit: 利確比率（例: 0.005 = 0.5%）
        stop_loss: 損切り比率（例: 0.003 = 0.3%）
        fee_rate: 往復手数料率
        direction: "long" or "short"

    Returns:
        list: トレード結果リスト
    """
    trades = []
    active_entry_indices = set()

    for sig_idx in signals:
        entry_idx = sig_idx
        if entry_idx >= len(candles) - 1:
            continue
        if entry_idx in active_entry_indices:
            continue

        entry_price = candles[entry_idx]["close"]
        entry_time = candles[entry_idx]["datetime"]

        exit_idx = None
        exit_price = None
        exit_reason = "hold_expired"

        # TP/SL チェック（以降のバーを順に確認）
        for j in range(entry_idx + 1, min(entry_idx + hold_bars + 1, len(candles))):
            high = candles[j]["high"]
            low = candles[j]["low"]

            if direction == "long":
                if take_profit and high >= entry_price * (1 + take_profit):
                    exit_price = entry_price * (1 + take_profit)
                    exit_idx = j
                    exit_reason = "take_profit"
                    break
                if stop_loss and low <= entry_price * (1 - stop_loss):
                    exit_price = entry_price * (1 - stop_loss)
                    exit_idx = j
                    exit_reason = "stop_loss"
                    break
            else:  # short
                if take_profit and low <= entry_price * (1 - take_profit):
                    exit_price = entry_price * (1 - take_profit)
                    exit_idx = j
                    exit_reason = "take_profit"
                    break
                if stop_loss and high >= entry_price * (1 + stop_loss):
                    exit_price = entry_price * (1 + stop_loss)
                    exit_idx = j
                    exit_reason = "stop_loss"
                    break

        if exit_idx is None:
            exit_idx = min(entry_idx + hold_bars, len(candles) - 1)
            exit_price = candles[exit_idx]["close"]

        exit_time = candles[exit_idx]["datetime"]

        if direction == "long":
            gross_pnl = (exit_price - entry_price) / entry_price
        else:
            gross_pnl = (entry_price - exit_price) / entry_price

        net_pnl = gross_pnl - fee_rate * 2  # 往復手数料

        trades.append({
            "entry_index": entry_idx,
            "exit_index": exit_idx,
            "entry_price": round(entry_price, 5),
            "exit_price": round(exit_price, 5),
            "entry_time": entry_time,
            "exit_time": exit_time,
            "gross_pnl_pct": round(gross_pnl * 100, 4),
            "net_pnl_pct": round(net_pnl * 100, 4),
            "win": net_pnl > 0,
            "exit_reason": exit_reason,
        })

        active_entry_indices.add(entry_idx)

    return trades


def calculate_stats(trades: list) -> dict:
    """トレード統計を計算する。"""
    if not trades:
        return {
            "total_trades": 0, "wins": 0, "losses": 0,
            "win_rate_pct": 0, "profit_factor": 0,
            "total_return_pct": 0, "avg_win_pct": 0, "avg_loss_pct": 0,
            "max_drawdown_pct": 0, "sharpe_ratio": 0,
            "equity_curve": [],
        }

    wins = [t for t in trades if t["win"]]
    losses = [t for t in trades if not t["win"]]

    total_profit = sum(t["net_pnl_pct"] for t in wins) if wins else 0
    total_loss = abs(sum(t["net_pnl_pct"] for t in losses)) if losses else 0

    profit_factor = total_profit / total_loss if total_loss > 0 else float("inf")

    # エクイティカーブ
    equity = [0.0]
    for t in trades:
        equity.append(equity[-1] + t["net_pnl_pct"])

    # 最大ドローダウン
    peak = 0.0
    max_dd = 0.0
    for e in equity:
        if e > peak:
            peak = e
        dd = peak - e
        if dd > max_dd:
            max_dd = dd

    # シャープレシオ（簡易計算）
    returns = [t["net_pnl_pct"] for t in trades]
    if len(returns) > 1:
        import statistics
        mean_r = statistics.mean(returns)
        std_r = statistics.stdev(returns)
        sharpe = mean_r / std_r if std_r > 0 else 0.0
    else:
        sharpe = 0.0

    return {
        "total_trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(len(wins) / len(trades) * 100, 1) if trades else 0,
        "profit_factor": round(profit_factor, 2),
        "total_return_pct": round(equity[-1], 4),
        "avg_win_pct": round(total_profit / len(wins), 4) if wins else 0,
        "avg_loss_pct": round(-total_loss / len(losses), 4) if losses else 0,
        "max_drawdown_pct": round(max_dd, 4),
        "sharpe_ratio": round(sharpe, 3),
        "equity_curve": [round(e, 4) for e in equity],
    }


# ─── メイン ───

def main():
    parser = argparse.ArgumentParser(description="FX バックテスト実行（MA+RSI ルールベース）")
    parser.add_argument("--symbol", default="USD-JPY", help="通貨ペア（strategy_config のキー表記）")
    parser.add_argument("--strategy", default="all", help="実行する戦略 ID (all / double_bottom / rsi_oversold_bounce)")
    parser.add_argument("--exchange", default="saxo_sim", help="saxo_sim or saxo")
    args = parser.parse_args()

    print("=" * 60)
    print("  FX バックテスト実行（MA+RSI ルールベース）")
    print(f"  Symbol  : {args.symbol}")
    print(f"  Strategy: {args.strategy}")
    print(f"  Exchange: {args.exchange}")
    print("=" * 60)

    # strategy_config.json 読み込み
    with open(STRATEGY_CONFIG_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)

    symbol_config = config["currencies"].get(args.symbol)
    if not symbol_config:
        print(f"[ERROR] strategy_config.json に {args.symbol} が見つかりません。")
        sys.exit(1)

    # OHLCV データ読み込み
    saxo_sym = args.symbol.replace("-", "").replace("/", "").upper()
    json_path = os.path.join(OHLCV_DIR, f"{saxo_sym}_1d.json")
    if not os.path.exists(json_path):
        print(f"[ERROR] OHLCV データが見つかりません: {json_path}")
        print(f"  先に fetch_fx_ohlcv.py を実行してデータを取得してください。")
        sys.exit(1)

    with open(json_path, "r", encoding="utf-8") as f:
        candles = json.load(f)

    print(f"\nOHLCV データ: {len(candles)}本 ({candles[0]['datetime']} 〜 {candles[-1]['datetime']})")

    # 出力ディレクトリ
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = os.path.join(RESULTS_DIR, f"fx_backtest_{saxo_sym}_1year_{timestamp}")
    os.makedirs(run_dir, exist_ok=True)
    os.makedirs(REPORT_DIR, exist_ok=True)

    # 戦略フィルター
    strategies = symbol_config.get("strategies", [])
    if args.strategy != "all":
        strategies = [s for s in strategies if s["id"] == args.strategy]

    if not strategies:
        print(f"[ERROR] 実行対象の戦略が見つかりません: {args.strategy}")
        sys.exit(1)

    all_results = []

    for strategy in strategies:
        strat_id = strategy["id"]
        pattern = strategy["pattern"]
        direction = strategy.get("direction", "long")
        hold_bars = strategy.get("hold_bars", 10)
        take_profit = strategy.get("take_profit")
        stop_loss = strategy.get("stop_loss")
        trend_filter = strategy.get("trend_filter", False)

        print(f"\n{'─' * 60}")
        print(f"  戦略: {strat_id} ({pattern})")
        print(f"  TP={take_profit}, SL={stop_loss}, Hold={hold_bars}bars, TrendFilter={trend_filter}")
        print(f"{'─' * 60}")

        # シグナル検出
        if "rsi_oversold" in pattern:
            signals = detect_rsi_oversold_bounce(candles)
        elif "double_bottom" in pattern:
            signals = detect_double_bottom_rule_based(
                candles, trend_filter=trend_filter
            )
        else:
            logger.warning(f"未対応パターン: {pattern}。RSI Oversold Bounce にフォールバック")
            signals = detect_rsi_oversold_bounce(candles)

        print(f"  シグナル数: {len(signals)}件")

        # バックテスト実行
        trades = run_strategy_backtest(
            candles,
            signals,
            hold_bars=hold_bars,
            take_profit=take_profit,
            stop_loss=stop_loss,
            fee_rate=0.00005,  # FX スプレッドコスト相当（0.005%片道）
            direction=direction,
        )

        # 統計計算
        stats = calculate_stats(trades)

        # 結果表示
        print(f"\n  --- 結果 ---")
        print(f"  トレード数  : {stats['total_trades']}")
        print(f"  勝率       : {stats['win_rate_pct']:.1f}%")
        print(f"  PF         : {stats['profit_factor']:.2f}")
        print(f"  総リターン  : {stats['total_return_pct']:.4f}%")
        print(f"  Avg Win    : {stats['avg_win_pct']:.4f}%")
        print(f"  Avg Loss   : {stats['avg_loss_pct']:.4f}%")
        print(f"  最大DD     : {stats['max_drawdown_pct']:.4f}%")
        print(f"  シャープ   : {stats['sharpe_ratio']:.3f}")

        strat_result = {
            "strategy_id": strat_id,
            "pattern": pattern,
            "config": {
                "direction": direction,
                "hold_bars": hold_bars,
                "take_profit": take_profit,
                "stop_loss": stop_loss,
                "trend_filter": trend_filter,
                "fee_rate": 0.00005,
            },
            "stats": stats,
            "trades": trades,
        }
        all_results.append(strat_result)

    # 全結果を保存
    full_result = {
        "symbol": args.symbol,
        "exchange": args.exchange,
        "data_period": f"{candles[0]['datetime']} 〜 {candles[-1]['datetime']}",
        "total_candles": len(candles),
        "run_timestamp": timestamp,
        "strategies": all_results,
    }

    result_json_path = os.path.join(run_dir, "result.json")
    with open(result_json_path, "w", encoding="utf-8") as f:
        json.dump(full_result, f, indent=2, ensure_ascii=False)
    print(f"\nJSON 結果: {result_json_path}")

    # マークダウンレポート生成
    report_path = os.path.join(REPORT_DIR, f"backtest_report_{saxo_sym}_1year.md")
    write_markdown_report(full_result, report_path, candles)
    print(f"MD レポート: {report_path}")

    print("\n" + "=" * 60)
    print("  バックテスト完了")
    print("=" * 60)

    return full_result


def write_markdown_report(result: dict, report_path: str, candles: list) -> None:
    """バックテスト結果をマークダウン形式でレポート出力する。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    symbol = result["symbol"]
    exchange = result["exchange"]
    period = result["data_period"]
    total_candles = result["total_candles"]

    lines = [
        f"# FX バックテストレポート: {symbol}",
        "",
        f"**生成日時**: {now}",
        f"**取引所**: {exchange}",
        f"**対象期間**: {period}",
        f"**データ本数**: {total_candles}本（日足）",
        "",
        "---",
        "",
        "## 戦略別結果サマリー",
        "",
        "| 戦略 | トレード数 | 勝率 | PF | 総リターン | 最大DD | シャープ |",
        "|------|-----------|------|----|-----------|--------|---------|",
    ]

    for strat in result["strategies"]:
        s = strat["stats"]
        lines.append(
            f"| {strat['strategy_id']} "
            f"| {s['total_trades']} "
            f"| {s['win_rate_pct']:.1f}% "
            f"| {s['profit_factor']:.2f} "
            f"| {s['total_return_pct']:.4f}% "
            f"| {s['max_drawdown_pct']:.4f}% "
            f"| {s['sharpe_ratio']:.3f} |"
        )

    lines += ["", "---", ""]

    for strat in result["strategies"]:
        s = strat["stats"]
        cfg = strat["config"]
        lines += [
            f"## 戦略詳細: {strat['strategy_id']}",
            "",
            f"**パターン**: {strat['pattern']}",
            f"**方向**: {cfg['direction']}",
            f"**保有期間**: {cfg['hold_bars']} バー",
            f"**TP**: {cfg['take_profit'] or 'なし'} ({float(cfg['take_profit'] or 0)*100:.2f}%)",
            f"**SL**: {cfg['stop_loss'] or 'なし'} ({float(cfg['stop_loss'] or 0)*100:.2f}%)",
            f"**トレンドフィルター**: {cfg['trend_filter']}",
            "",
            "### 主要指標",
            "",
            f"- トレード数: **{s['total_trades']}**",
            f"- 勝数 / 敗数: {s['wins']} / {s['losses']}",
            f"- 勝率: **{s['win_rate_pct']:.1f}%**",
            f"- プロフィットファクター: **{s['profit_factor']:.2f}**",
            f"- 総リターン: **{s['total_return_pct']:.4f}%**",
            f"- 平均利益: {s['avg_win_pct']:.4f}%",
            f"- 平均損失: {s['avg_loss_pct']:.4f}%",
            f"- 最大ドローダウン: **{s['max_drawdown_pct']:.4f}%**",
            f"- シャープレシオ: {s['sharpe_ratio']:.3f}",
            "",
        ]

        # 個別トレード（最大20件表示）
        trades = strat.get("trades", [])
        if trades:
            lines += [
                "### トレード詳細（最大20件）",
                "",
                "| # | エントリー日 | エグジット日 | エントリー価格 | エグジット価格 | PnL% | 理由 |",
                "|---|------------|------------|--------------|--------------|------|------|",
            ]
            for idx, t in enumerate(trades[:20], 1):
                win_mark = "○" if t["win"] else "×"
                lines.append(
                    f"| {idx} | {t['entry_time'][:10]} | {t['exit_time'][:10]} "
                    f"| {t['entry_price']:.3f} | {t['exit_price']:.3f} "
                    f"| {win_mark} {t['net_pnl_pct']:+.4f}% | {t['exit_reason']} |"
                )
            if len(trades) > 20:
                lines.append(f"\n*（他 {len(trades)-20} 件省略）*")
            lines.append("")

        lines += ["---", ""]

    lines += [
        "## 免責事項",
        "",
        "本バックテストは過去データに基づくシミュレーションです。",
        "将来の運用成績を保証するものではありません。",
        "Saxo Bank Sim 環境での検証結果であり、本番環境での結果は異なる場合があります。",
        "",
    ]

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    logger.info(f"マークダウンレポート保存: {report_path}")


if __name__ == "__main__":
    main()
