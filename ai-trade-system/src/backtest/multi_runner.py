"""
マルチ通貨バックテストランナー
strategy_config.json に基づき、通貨ごとに最適プロンプトを自動選択して実行
"""
import os
import sys
import json
import glob
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backtest.runner import run_backtest

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "strategy_config.json")
DATA_DIR = os.path.join(os.path.dirname(__file__), "../../data/ohlcv")


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def get_pattern_for_currency(config, currency_pair):
    """通貨ペアに対応するパターン名を返す"""
    pair_key = currency_pair.replace("_", "-").split("_")[0]
    # ファイル名から通貨ペアを抽出 (e.g., "BTC-USDT_1d_1000.json" -> "BTC-USDT")
    for key, val in config["currencies"].items():
        if pair_key.startswith(key):
            if val["pattern"] == "pending":
                return config["default"]["pattern"]
            return val["pattern"]
    return config["default"]["pattern"]


def run_multi(timeframe="1d", currencies=None, api_delay=1.0):
    """
    全通貨（または指定通貨）のバックテストを順次実行

    Args:
        timeframe: 時間足フィルタ (e.g., "1d", "4h", "1h")
        currencies: 実行する通貨リスト (e.g., ["BTC", "ETH"])。Noneで全通貨
        api_delay: API呼び出し間隔
    """
    config = load_config()
    defaults = config["default"]

    # データファイル検索
    pattern = os.path.join(DATA_DIR, f"*_{timeframe}_*.json")
    data_files = sorted(glob.glob(pattern))

    if not data_files:
        print(f"No data files found for timeframe: {timeframe}")
        return

    # 通貨フィルタ
    if currencies:
        currencies_upper = [c.upper() for c in currencies]
        data_files = [
            f for f in data_files
            if any(c in os.path.basename(f).upper() for c in currencies_upper)
        ]

    print("=" * 60)
    print(f"  Multi-Currency Backtest")
    print(f"  Timeframe: {timeframe}")
    print(f"  Currencies: {len(data_files)}")
    print("=" * 60)

    results = []
    for i, data_file in enumerate(data_files, 1):
        basename = os.path.basename(data_file)
        pair = basename.split("_")[0]
        prompt = get_pattern_for_currency(config, pair)

        print(f"\n{'#' * 60}")
        print(f"  [{i}/{len(data_files)}] {pair} -> {prompt}")
        print(f"{'#' * 60}")

        result = run_backtest(
            data_file,
            pattern_name=prompt,
            window_size=defaults["window_size"],
            step=defaults["step"],
            hold_bars=defaults["hold_bars"],
            fee_rate=defaults["fee_rate"],
            api_delay=api_delay,
            direction=defaults["direction"],
        )

        results.append({
            "currency": pair,
            "pattern": prompt,
            "stats": result["stats"],
        })

    # サマリーテーブル
    print("\n" + "=" * 60)
    print("  MULTI-CURRENCY SUMMARY")
    print("=" * 60)
    print(f"  {'Currency':<12} {'Pattern':<30} {'Trades':>6} {'WinR':>6} {'PF':>6} {'Return':>8} {'MaxDD':>8}")
    print("-" * 60)
    for r in results:
        s = r["stats"]
        print(
            f"  {r['currency']:<12} {r['pattern']:<30} "
            f"{s['total_trades']:>6} "
            f"{s['win_rate_pct']:>5.1f}% "
            f"{s['profit_factor']:>6.2f} "
            f"{s['total_return_pct']:>7.2f}% "
            f"{s['max_drawdown_pct']:>7.2f}%"
        )
    print("=" * 60)

    # サマリーJSON保存
    summary_path = os.path.join(
        os.path.dirname(__file__), "../../results",
        f"multi_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nSummary saved: {summary_path}")

    return results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Multi-currency backtest")
    parser.add_argument("--timeframe", default="1d", help="Timeframe filter (e.g., 1d, 4h)")
    parser.add_argument("--currencies", nargs="*", help="Currency filter (e.g., BTC ETH)")
    parser.add_argument("--delay", type=float, default=1.0, help="API delay (sec)")
    args = parser.parse_args()

    run_multi(
        timeframe=args.timeframe,
        currencies=args.currencies,
        api_delay=args.delay,
    )
