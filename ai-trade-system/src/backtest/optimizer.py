"""
既存のバックテスト結果（判定済み）を使って、
利確/損切りライン・保有期間を変えてP&Lを再計算するオプティマイザー

v2: DD重視スコアリング（Calmar比率）、拡張グリッド、DD制約付き最適化
"""
import os
import json
import sys
import glob

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def load_result(result_json_path):
    with open(result_json_path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_candles(data_dir, config):
    """OHLCVデータを読み込む"""
    ohlcv_dir = os.path.join(data_dir, "ohlcv")
    json_path = os.path.join(ohlcv_dir, config["data_file"])
    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)


def recalculate_pnl(
    candles,
    metadata,
    config,
    take_profit=None,
    stop_loss=None,
    hold_bars=20,
    fee_rate=0.001,
    direction="long",
):
    """
    利確/損切りラインを考慮した損益再計算

    Args:
        candles: 全ローソク足データ
        metadata: 判定メタデータ（detected付き）
        config: バックテスト設定
        take_profit: 利確ライン（例: 0.03 = 3%）、Noneなら利確なし
        stop_loss: 損切りライン（例: 0.02 = 2%）、Noneなら損切りなし
        hold_bars: 最大保有期間
        fee_rate: 片道手数料率
        direction: "long" or "short"
    """
    window_size = config["window_size"]
    trades = []

    for meta in metadata:
        if meta.get("detected") != 1:
            continue

        entry_idx = meta["index"] + window_size - 1
        max_exit_idx = entry_idx + hold_bars

        if max_exit_idx >= len(candles):
            continue

        entry_price = candles[entry_idx]["close"]

        # 各バーを確認して利確/損切り判定
        exit_idx = max_exit_idx  # デフォルトは最大保有期間
        exit_reason = "timeout"

        for bar_idx in range(entry_idx + 1, max_exit_idx + 1):
            if bar_idx >= len(candles):
                break

            bar = candles[bar_idx]

            if direction == "long":
                # 高値で利確判定、安値で損切り判定
                high_pnl = (bar["high"] - entry_price) / entry_price
                low_pnl = (bar["low"] - entry_price) / entry_price

                if stop_loss is not None and low_pnl <= -stop_loss:
                    exit_idx = bar_idx
                    exit_reason = "stop_loss"
                    break
                if take_profit is not None and high_pnl >= take_profit:
                    exit_idx = bar_idx
                    exit_reason = "take_profit"
                    break
            else:
                high_pnl = (entry_price - bar["low"]) / entry_price
                low_pnl = (entry_price - bar["high"]) / entry_price

                if stop_loss is not None and low_pnl <= -stop_loss:
                    exit_idx = bar_idx
                    exit_reason = "stop_loss"
                    break
                if take_profit is not None and high_pnl >= take_profit:
                    exit_idx = bar_idx
                    exit_reason = "take_profit"
                    break

        # 損益計算
        exit_price = candles[exit_idx]["close"]
        if exit_reason == "take_profit":
            gross_pnl = take_profit if direction == "long" else take_profit
        elif exit_reason == "stop_loss":
            gross_pnl = -stop_loss if direction == "long" else -stop_loss
        else:
            if direction == "long":
                gross_pnl = (exit_price - entry_price) / entry_price
            else:
                gross_pnl = (entry_price - exit_price) / entry_price

        net_pnl = gross_pnl - fee_rate * 2

        trade = {
            "entry_index": entry_idx,
            "exit_index": exit_idx,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "net_pnl_pct": round(net_pnl * 100, 4),
            "win": net_pnl > 0,
            "exit_reason": exit_reason,
            "chart_image": meta.get("file", ""),
        }
        trades.append(trade)

    return trades, calculate_stats(trades)


def calculate_stats(trades):
    if not trades:
        return {"total_trades": 0, "win_rate_pct": 0, "profit_factor": 0,
                "total_return_pct": 0, "avg_win_pct": 0, "avg_loss_pct": 0,
                "max_drawdown_pct": 0}

    wins = [t for t in trades if t["win"]]
    losses = [t for t in trades if not t["win"]]
    total_profit = sum(t["net_pnl_pct"] for t in wins) if wins else 0
    total_loss = abs(sum(t["net_pnl_pct"] for t in losses)) if losses else 0
    pf = total_profit / total_loss if total_loss > 0 else float("inf")

    equity = [0]
    for t in trades:
        equity.append(equity[-1] + t["net_pnl_pct"])
    peak = 0
    max_dd = 0
    for e in equity:
        if e > peak: peak = e
        dd = peak - e
        if dd > max_dd: max_dd = dd

    # 損切り・利確・タイムアウト内訳
    tp_count = sum(1 for t in trades if t.get("exit_reason") == "take_profit")
    sl_count = sum(1 for t in trades if t.get("exit_reason") == "stop_loss")
    to_count = sum(1 for t in trades if t.get("exit_reason") == "timeout")

    return {
        "total_trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(len(wins) / len(trades) * 100, 1),
        "profit_factor": round(pf, 2),
        "total_return_pct": round(equity[-1], 2),
        "avg_win_pct": round(total_profit / len(wins), 2) if wins else 0,
        "avg_loss_pct": round(-total_loss / len(losses), 2) if losses else 0,
        "max_drawdown_pct": round(max_dd, 2),
        "tp_count": tp_count,
        "sl_count": sl_count,
        "timeout_count": to_count,
    }


def calmar_score(stats, min_trades=5):
    """Calmar比率ベースのスコア（Return / MaxDD）。DD0は無限大回避"""
    if stats["total_trades"] < min_trades:
        return -999
    if stats["max_drawdown_pct"] <= 0:
        return stats["total_return_pct"] * 100 if stats["total_return_pct"] > 0 else 0
    return stats["total_return_pct"] / stats["max_drawdown_pct"]


def grid_search(result_json_path, data_dir, max_dd=None, extended=False):
    """
    利確/損切り/保有期間のグリッドサーチ

    Args:
        result_json_path: バックテスト結果JSONのパス
        data_dir: データディレクトリ
        max_dd: DD上限制約（例: 30 = 30%以下）。Noneなら制約なし
        extended: Trueで拡張グリッド（より細かい刻み）
    """
    data = load_result(result_json_path)
    config = data["config"]
    metadata = data["metadata"]
    candles = load_candles(data_dir, config)

    # グリッドサーチパラメータ
    if extended:
        tp_values = [None, 0.01, 0.015, 0.02, 0.025, 0.03, 0.04, 0.05, 0.06, 0.08, 0.10]
        sl_values = [None, 0.005, 0.01, 0.015, 0.02, 0.025, 0.03, 0.04, 0.05]
        hold_values = [5, 10, 15, 20, 25, 30, 40, 50]
    else:
        tp_values = [None, 0.02, 0.03, 0.05, 0.08]
        sl_values = [None, 0.01, 0.02, 0.03, 0.05]
        hold_values = [10, 20, 30, 50]

    results = []
    total_combos = len(tp_values) * len(sl_values) * len(hold_values)
    print(f"Grid search: {len(tp_values)}x{len(sl_values)}x{len(hold_values)} = {total_combos} combinations")
    print(f"Pattern: {config['pattern']} | Direction: {config.get('direction','long')}")
    if max_dd:
        print(f"DD constraint: <= {max_dd}%")
    print()

    for hold in hold_values:
        for tp in tp_values:
            for sl in sl_values:
                trades, stats = recalculate_pnl(
                    candles, metadata, config,
                    take_profit=tp, stop_loss=sl,
                    hold_bars=hold, fee_rate=config.get("fee_rate", 0.001),
                    direction=config.get("direction", "long"),
                )

                entry = {
                    "take_profit": tp,
                    "stop_loss": sl,
                    "hold_bars": hold,
                    "calmar": round(calmar_score(stats), 3),
                    **stats,
                }
                results.append(entry)

    # --- ランキング表示 ---
    def fmt_row(r):
        tp_str = f"{r['take_profit']*100:.1f}%" if r['take_profit'] else "None"
        sl_str = f"{r['stop_loss']*100:.1f}%" if r['stop_loss'] else "None"
        return (f"{tp_str:>7} {sl_str:>7} {r['hold_bars']:>5} {r['total_trades']:>6} "
                f"{r['win_rate_pct']:>6.1f}% {r['profit_factor']:>6.2f} "
                f"{r['total_return_pct']:>8.2f}% {r['max_drawdown_pct']:>7.2f}% "
                f"{r['calmar']:>7.3f}")

    header = f"{'TP':>7} {'SL':>7} {'Hold':>5} {'Trd':>6} {'WinR%':>7} {'PF':>7} {'Return%':>9} {'MaxDD%':>8} {'Calmar':>7}"
    sep = "-" * 75

    # 1) ベスト by Calmar（DD制約なし）
    by_calmar = sorted([r for r in results if r["total_trades"] >= 5],
                       key=lambda x: x["calmar"], reverse=True)
    print("=" * 75)
    print("TOP 10 by Calmar Ratio (Return / MaxDD)")
    print("=" * 75)
    print(header)
    print(sep)
    for r in by_calmar[:10]:
        print(fmt_row(r))

    # 2) ベスト by PF
    by_pf = sorted([r for r in results if r["total_trades"] >= 5],
                   key=lambda x: x["profit_factor"], reverse=True)
    print(f"\n{'=' * 75}")
    print("TOP 10 by Profit Factor")
    print("=" * 75)
    print(header)
    print(sep)
    for r in by_pf[:10]:
        print(fmt_row(r))

    # 3) DD制約付きベスト
    if max_dd:
        dd_filtered = [r for r in results
                       if r["total_trades"] >= 5 and r["max_drawdown_pct"] <= max_dd]
        by_calmar_dd = sorted(dd_filtered, key=lambda x: x["calmar"], reverse=True)
        print(f"\n{'=' * 75}")
        print(f"TOP 10 with MaxDD <= {max_dd}% (by Calmar)")
        print("=" * 75)
        print(header)
        print(sep)
        if by_calmar_dd:
            for r in by_calmar_dd[:10]:
                print(fmt_row(r))
        else:
            print(f"  No combinations found with DD <= {max_dd}%")

    # サマリー
    print(f"\n{'=' * 75}")
    print("RECOMMENDATIONS")
    print("=" * 75)
    if by_calmar:
        r = by_calmar[0]
        print(f"  Best Calmar: TP={r['take_profit']}, SL={r['stop_loss']}, Hold={r['hold_bars']}")
        print(f"    → PF={r['profit_factor']:.2f}, Return={r['total_return_pct']:.2f}%, DD={r['max_drawdown_pct']:.2f}%, Calmar={r['calmar']:.3f}")
    if max_dd and by_calmar_dd:
        r = by_calmar_dd[0]
        print(f"  Best (DD<={max_dd}%): TP={r['take_profit']}, SL={r['stop_loss']}, Hold={r['hold_bars']}")
        print(f"    → PF={r['profit_factor']:.2f}, Return={r['total_return_pct']:.2f}%, DD={r['max_drawdown_pct']:.2f}%, Calmar={r['calmar']:.3f}")

    # 全結果保存
    out_dir = os.path.dirname(result_json_path)
    out_path = os.path.join(out_dir, "grid_search_results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nAll results saved: {out_path}")

    return results


def optimize_all(results_dir, data_dir, max_dd=30):
    """
    全通貨の最新結果を一括最適化し、推奨パラメータをまとめて出力する

    Args:
        results_dir: results/ ディレクトリ
        data_dir: data/ ディレクトリ
        max_dd: DD上限制約（%）
    """
    # 通貨ごとの最新結果ファイルを検索（1d のみ対象）
    currency_best = {}  # currency -> (timestamp, path)
    for d in sorted(glob.glob(os.path.join(results_dir, "backtest_*"))):
        result_path = os.path.join(d, "result.json")
        if not os.path.isfile(result_path):
            continue
        with open(result_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        data_file = data["config"]["data_file"]
        if "_1d_" not in data_file:
            continue
        currency = data_file.split("_")[0]  # e.g., "BTC-USDT"
        pattern = data["config"]["pattern"]
        # 通貨別最適パターンの結果のみ（strategy_config.json に合致するもの）
        config_path = os.path.join(os.path.dirname(__file__), "strategy_config.json")
        with open(config_path, "r", encoding="utf-8") as f:
            strategy_config = json.load(f)
        expected_pattern = strategy_config["currencies"].get(currency, {}).get("pattern",
                          strategy_config["default"]["pattern"])
        if pattern != expected_pattern:
            continue
        ts = os.path.basename(d)
        if currency not in currency_best or ts > currency_best[currency][0]:
            currency_best[currency] = (ts, result_path)

    if not currency_best:
        print("No matching result files found.")
        return {}

    print("=" * 80)
    print("  MULTI-CURRENCY TP/SL OPTIMIZATION")
    print(f"  DD Constraint: <= {max_dd}%")
    print("=" * 80)

    recommendations = {}
    for currency in sorted(currency_best.keys()):
        ts, result_path = currency_best[currency]
        data = load_result(result_path)
        config = data["config"]
        print(f"\n{'#' * 80}")
        print(f"  {currency} | Pattern: {config['pattern']} | Source: {ts}")
        print(f"{'#' * 80}")

        results = grid_search(result_path, data_dir, max_dd=max_dd, extended=True)

        # 推奨パラメータ抽出
        valid = [r for r in results if r["total_trades"] >= 5 and r["max_drawdown_pct"] <= max_dd]
        if valid:
            best = max(valid, key=lambda x: x["calmar"])
        else:
            best = max([r for r in results if r["total_trades"] >= 5],
                       key=lambda x: x["calmar"], default=None)

        if best:
            recommendations[currency] = {
                "take_profit": best["take_profit"],
                "stop_loss": best["stop_loss"],
                "hold_bars": best["hold_bars"],
                "profit_factor": best["profit_factor"],
                "total_return_pct": best["total_return_pct"],
                "max_drawdown_pct": best["max_drawdown_pct"],
                "calmar": best["calmar"],
                "win_rate_pct": best["win_rate_pct"],
                "total_trades": best["total_trades"],
                "dd_within_limit": best["max_drawdown_pct"] <= max_dd,
            }

    # 全通貨サマリー
    print(f"\n{'=' * 80}")
    print("  FINAL RECOMMENDATIONS (All Currencies)")
    print(f"{'=' * 80}")
    print(f"  {'Currency':<12} {'TP':>7} {'SL':>7} {'Hold':>5} {'PF':>6} {'Ret%':>8} {'DD%':>7} {'Calmar':>7} {'OK':>4}")
    print("-" * 80)
    for currency in sorted(recommendations.keys()):
        r = recommendations[currency]
        tp_str = f"{r['take_profit']*100:.1f}%" if r['take_profit'] else "None"
        sl_str = f"{r['stop_loss']*100:.1f}%" if r['stop_loss'] else "None"
        ok = "v" if r["dd_within_limit"] else "x"
        print(f"  {currency:<12} {tp_str:>7} {sl_str:>7} {r['hold_bars']:>5} "
              f"{r['profit_factor']:>6.2f} {r['total_return_pct']:>7.2f}% "
              f"{r['max_drawdown_pct']:>6.2f}% {r['calmar']:>7.3f} {ok:>4}")

    # 推奨パラメータ保存
    out_path = os.path.join(results_dir, "optimization_recommendations.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(recommendations, f, indent=2, ensure_ascii=False)
    print(f"\nRecommendations saved: {out_path}")

    return recommendations


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Optimize TP/SL/Hold parameters")
    parser.add_argument("result_json", nargs="?", help="Path to result.json (single mode)")
    parser.add_argument("--data-dir", default=None, help="Data directory (default: auto)")
    parser.add_argument("--max-dd", type=float, default=30, help="Max drawdown constraint (%%)")
    parser.add_argument("--extended", action="store_true", help="Extended grid search")
    parser.add_argument("--all", action="store_true", help="Optimize all currencies")
    args = parser.parse_args()

    if args.data_dir is None:
        args.data_dir = os.path.join(os.path.dirname(__file__), "../../data")

    if args.all:
        results_dir = os.path.join(os.path.dirname(__file__), "../../results")
        optimize_all(results_dir, args.data_dir, max_dd=args.max_dd)
    elif args.result_json:
        grid_search(args.result_json, args.data_dir, max_dd=args.max_dd, extended=args.extended)
    else:
        print("Usage: optimizer.py result.json  OR  optimizer.py --all")
        print("  --max-dd 30    : DD constraint (default: 30%)")
        print("  --extended     : Fine-grained grid search")
        print("  --all          : Optimize all currencies at once")
