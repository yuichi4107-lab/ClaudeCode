"""
画像生成済みのバックテストを途中から再開する
(画像生成をスキップしてAI判定→損益計算のみ実行)
"""
import os
import sys
import json
import time
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from ai.gemini_client import judge_batch
from backtest.runner import calculate_stats


def resume(run_dir, pattern_name, json_path, hold_bars=20, fee_rate=0.001, direction="long", api_delay=1.0):
    charts_dir = os.path.join(run_dir, "charts")
    meta_path = os.path.join(charts_dir, "_metadata.json")

    with open(meta_path, "r") as f:
        metadata = json.load(f)

    with open(json_path, "r") as f:
        all_candles = json.load(f)

    print(f"Pattern: {pattern_name}")
    print(f"Images: {len(metadata)}")

    # 判定
    image_paths = [os.path.join(charts_dir, m["file"]) for m in metadata]
    judgments = judge_batch(image_paths, pattern_name, api_delay)

    for meta, judgment in zip(metadata, judgments):
        meta["detected"] = judgment["detected"]
        meta["raw_response"] = judgment.get("raw_response", "")

    # 損益計算
    window_size = 50
    trades = []
    for meta in metadata:
        if meta["detected"] != 1:
            continue
        entry_idx = meta["index"] + window_size - 1
        exit_idx = entry_idx + hold_bars
        if exit_idx >= len(all_candles):
            continue
        entry_price = all_candles[entry_idx]["close"]
        exit_price = all_candles[exit_idx]["close"]
        if direction == "long":
            gross_pnl = (exit_price - entry_price) / entry_price
        else:
            gross_pnl = (entry_price - exit_price) / entry_price
        net_pnl = gross_pnl - fee_rate * 2

        trades.append({
            "entry_index": entry_idx, "exit_index": exit_idx,
            "entry_price": entry_price, "exit_price": exit_price,
            "entry_time": all_candles[entry_idx].get("datetime", ""),
            "exit_time": all_candles[exit_idx].get("datetime", ""),
            "gross_pnl_pct": round(gross_pnl * 100, 4),
            "net_pnl_pct": round(net_pnl * 100, 4),
            "win": net_pnl > 0,
            "chart_image": meta["file"],
        })

    stats = calculate_stats(trades)

    result = {
        "config": {
            "data_file": os.path.basename(json_path),
            "pattern": pattern_name, "direction": direction,
            "window_size": window_size, "step": 5,
            "hold_bars": hold_bars, "fee_rate": fee_rate,
            "total_candles": len(all_candles), "total_images": len(metadata),
        },
        "stats": stats, "trades": trades, "metadata": metadata,
    }

    result_path = os.path.join(run_dir, "result.json")
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"\nSignals: {stats['total_trades']} | WinRate: {stats['win_rate_pct']:.1f}% | PF: {stats['profit_factor']:.2f} | Return: {stats['total_return_pct']:.2f}% | MaxDD: {stats['max_drawdown_pct']:.2f}%")
    print(f"Saved: {result_path}")
    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir")
    parser.add_argument("--pattern", required=True)
    parser.add_argument("--data", required=True)
    parser.add_argument("--hold", type=int, default=20)
    parser.add_argument("--delay", type=float, default=1.0)
    args = parser.parse_args()
    resume(args.run_dir, args.pattern, args.data, hold_bars=args.hold, api_delay=args.delay)
