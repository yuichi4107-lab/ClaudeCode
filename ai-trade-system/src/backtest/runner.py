"""
ステップ3: 自動バックテストシステム
画像生成 → Gemini判定 → 損益計算をワンストップで実行
"""
import os
import sys
import json
import time
from datetime import datetime

# パス設定
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from chart.generate_chart_images import generate_sliding_images, load_candles
from ai.gemini_client import judge_batch, setup_gemini, judge_chart_image

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "../../results")


def run_backtest(
    json_path,
    pattern_name="double_bottom",
    window_size=50,
    step=5,
    hold_bars=20,
    fee_rate=0.001,
    image_size=512,
    api_delay=1.0,
    direction="long",
):
    """
    フルバックテストを実行する。

    Args:
        json_path: OHLCVデータのJSONパス
        pattern_name: 判定パターン名
        window_size: 1画像に含むローソク足本数
        step: スライド幅
        hold_bars: シグナル後の保有期間（ローソク足本数）
        fee_rate: 片道手数料率（0.001 = 0.1%）
        image_size: 画像サイズ
        api_delay: API呼び出し間隔（秒）
        direction: "long"（買い）or "short"（売り）
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = os.path.join(RESULTS_DIR, f"backtest_{timestamp}")
    charts_dir = os.path.join(run_dir, "charts")
    os.makedirs(charts_dir, exist_ok=True)

    print("=" * 60)
    print(f"  Backtest: {pattern_name} ({direction})")
    print(f"  Window: {window_size} bars, Step: {step}, Hold: {hold_bars} bars")
    print(f"  Fee: {fee_rate*100:.2f}% per trade")
    print("=" * 60)

    # 1. 全ローソク足データ読み込み
    all_candles = load_candles(json_path)
    print(f"\nLoaded {len(all_candles)} candles")

    # 2. スライドウィンドウで画像生成
    print("\n--- Phase 1: Generating chart images ---")
    metadata = generate_sliding_images(
        json_path, window_size, step, image_size, charts_dir
    )

    # 3. Gemini判定
    print("\n--- Phase 2: AI pattern detection ---")
    image_paths = [os.path.join(charts_dir, m["file"]) for m in metadata]
    judgments = judge_batch(image_paths, pattern_name, api_delay)

    # メタデータと判定結果をマージ
    for meta, judgment in zip(metadata, judgments):
        meta["detected"] = judgment["detected"]
        meta["raw_response"] = judgment.get("raw_response", "")

    # 4. 損益計算
    print("\n--- Phase 3: Calculating P&L ---")
    trades = []
    for meta in metadata:
        if meta["detected"] != 1:
            continue

        entry_idx = meta["index"] + window_size - 1
        exit_idx = entry_idx + hold_bars

        if exit_idx >= len(all_candles):
            continue  # データ不足でスキップ

        entry_price = all_candles[entry_idx]["close"]
        exit_price = all_candles[exit_idx]["close"]

        if direction == "long":
            gross_pnl = (exit_price - entry_price) / entry_price
        else:
            gross_pnl = (entry_price - exit_price) / entry_price

        net_pnl = gross_pnl - fee_rate * 2  # 往復手数料

        trade = {
            "entry_index": entry_idx,
            "exit_index": exit_idx,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "entry_time": all_candles[entry_idx].get("datetime", ""),
            "exit_time": all_candles[exit_idx].get("datetime", ""),
            "gross_pnl_pct": round(gross_pnl * 100, 4),
            "net_pnl_pct": round(net_pnl * 100, 4),
            "win": net_pnl > 0,
            "chart_image": meta["file"],
        }
        trades.append(trade)

    # 5. 統計算出
    stats = calculate_stats(trades)

    # 6. 結果保存
    result = {
        "config": {
            "data_file": os.path.basename(json_path),
            "pattern": pattern_name,
            "direction": direction,
            "window_size": window_size,
            "step": step,
            "hold_bars": hold_bars,
            "fee_rate": fee_rate,
            "total_candles": len(all_candles),
            "total_images": len(metadata),
        },
        "stats": stats,
        "trades": trades,
        "metadata": metadata,
    }

    result_path = os.path.join(run_dir, "result.json")
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    # 7. サマリー表示
    print("\n" + "=" * 60)
    print("  BACKTEST RESULT")
    print("=" * 60)
    print(f"  Total images scanned : {len(metadata)}")
    print(f"  Signals detected     : {stats['total_trades']}")
    print(f"  Win rate             : {stats['win_rate_pct']:.1f}%")
    print(f"  Profit factor        : {stats['profit_factor']:.2f}")
    print(f"  Total return         : {stats['total_return_pct']:.2f}%")
    print(f"  Avg win              : {stats['avg_win_pct']:.2f}%")
    print(f"  Avg loss             : {stats['avg_loss_pct']:.2f}%")
    print(f"  Max drawdown         : {stats['max_drawdown_pct']:.2f}%")
    print("=" * 60)
    print(f"\nResults saved: {result_path}")

    return result


def calculate_stats(trades):
    """トレード結果から統計を算出"""
    if not trades:
        return {
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate_pct": 0,
            "profit_factor": 0,
            "total_return_pct": 0,
            "avg_win_pct": 0,
            "avg_loss_pct": 0,
            "max_drawdown_pct": 0,
            "equity_curve": [],
        }

    wins = [t for t in trades if t["win"]]
    losses = [t for t in trades if not t["win"]]

    total_profit = sum(t["net_pnl_pct"] for t in wins) if wins else 0
    total_loss = abs(sum(t["net_pnl_pct"] for t in losses)) if losses else 0

    profit_factor = total_profit / total_loss if total_loss > 0 else float("inf")

    # エクイティカーブ
    equity = [0]
    for t in trades:
        equity.append(equity[-1] + t["net_pnl_pct"])

    # 最大ドローダウン
    peak = 0
    max_dd = 0
    for e in equity:
        if e > peak:
            peak = e
        dd = peak - e
        if dd > max_dd:
            max_dd = dd

    return {
        "total_trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": len(wins) / len(trades) * 100 if trades else 0,
        "profit_factor": round(profit_factor, 2),
        "total_return_pct": round(equity[-1], 2),
        "avg_win_pct": round(total_profit / len(wins), 2) if wins else 0,
        "avg_loss_pct": round(-total_loss / len(losses), 2) if losses else 0,
        "max_drawdown_pct": round(max_dd, 2),
        "equity_curve": [round(e, 2) for e in equity],
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run full backtest")
    parser.add_argument("json_path", help="Path to OHLCV JSON file")
    parser.add_argument("--pattern", default="double_bottom", help="Pattern name")
    parser.add_argument("--window", type=int, default=50, help="Candles per image")
    parser.add_argument("--step", type=int, default=5, help="Slide step")
    parser.add_argument("--hold", type=int, default=20, help="Hold period (bars)")
    parser.add_argument("--fee", type=float, default=0.001, help="Fee rate (e.g. 0.001)")
    parser.add_argument("--delay", type=float, default=1.0, help="API call delay (sec)")
    parser.add_argument("--direction", default="long", choices=["long", "short"])
    args = parser.parse_args()

    run_backtest(
        args.json_path,
        pattern_name=args.pattern,
        window_size=args.window,
        step=args.step,
        hold_bars=args.hold,
        fee_rate=args.fee,
        api_delay=args.delay,
        direction=args.direction,
    )
