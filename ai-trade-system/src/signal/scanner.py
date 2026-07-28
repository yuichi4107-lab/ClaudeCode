"""
リアルタイムシグナルスキャナー

最新のOHLCVデータを取得し、AI判定でチャートパターンシグナルを検出する。
strategy_config.json に基づき、通貨別・戦略別の最適設定でスキャンする。
トレンドフィルター対応: 下落トレンド中はロング系シグナルをブロック。

使い方:
    python src/signal/scanner.py                    # 全4通貨スキャン
    python src/signal/scanner.py --symbols BTC/USDT # 個別通貨
    python src/signal/scanner.py --dry-run           # API呼び出しなし（データ取得のみ）
"""
import os
import sys
import json
import argparse
import tempfile
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))

import ccxt
import pandas as pd

# プロジェクトルートをパスに追加
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, PROJECT_ROOT)

from src.chart.generate_chart_images import draw_candlestick_chart
from src.ai.gemini_client import judge_chart_image, setup_gemini
from src.signal.trend_filter import check_trend_filter

CONFIG_PATH = os.path.join(PROJECT_ROOT, "src/backtest/strategy_config.json")
SIGNAL_LOG_DIR = os.path.join(PROJECT_ROOT, "data/signals")


def load_strategy_config():
    """strategy_config.json を読み込む"""
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def get_currency_strategies(config, symbol):
    """
    通貨の戦略リストを取得する（新旧フォーマット対応）。

    新フォーマット: currencies[symbol].strategies (配列)
    旧フォーマット: currencies[symbol].pattern (単一) → 配列に変換

    Returns:
        list of dict: 戦略設定のリスト
    """
    safe_symbol = symbol.replace("/", "-")
    currency_config = config["currencies"].get(safe_symbol, {})
    default_config = config["default"]

    # 新フォーマット: strategies 配列がある場合
    if "strategies" in currency_config:
        strategies = []
        for s in currency_config["strategies"]:
            # enabled: false の戦略をスキップ（存在しないか true の場合は含める）
            if s.get("enabled", True) is False:
                continue
            strategies.append({
                "id": s["id"],
                "pattern": s.get("pattern", default_config["pattern"]),
                "direction": s.get("direction", default_config.get("direction", "long")),
                "window_size": s.get("window_size", default_config["window_size"]),
                "take_profit": s.get("take_profit"),
                "stop_loss": s.get("stop_loss"),
                "hold_bars": s.get("hold_bars", default_config["hold_bars"]),
                "trend_filter": s.get("trend_filter", False),
                # bull trap ガード（BTC限定・デフォルト0=無効。他通貨はreentry_confirm_days未設定で不変）
                "reentry_confirm_days": s.get("reentry_confirm_days", 0),
            })
        return strategies

    # 旧フォーマット: 単一パターン → 配列に変換
    return [{
        "id": currency_config.get("pattern", default_config["pattern"]),
        "pattern": currency_config.get("pattern", default_config["pattern"]),
        "direction": default_config.get("direction", "long"),
        "window_size": currency_config.get("window_size", default_config["window_size"]),
        "take_profit": currency_config.get("take_profit"),
        "stop_loss": currency_config.get("stop_loss"),
        "hold_bars": currency_config.get("hold_bars", default_config["hold_bars"]),
        "trend_filter": True,  # 旧フォーマットのロング戦略はフィルター有効
    }]


def _is_fx_symbol(symbol):
    """FX通貨ペアかどうかを判定する（3文字/3文字の形式）"""
    parts = symbol.replace("-", "/").split("/")
    return len(parts) == 2 and len(parts[0]) == 3 and len(parts[1]) == 3


def fetch_latest_candles(symbol, timeframe="1d", limit=60, exchange_id="binance"):
    """
    取引所から最新のOHLCVデータを取得する。

    FX通貨ペア（3文字/3文字）の場合は exchange_id に応じて適切なクライアントから取得する。
    - saxo_sim / saxo 指定時: SaxoClient 経由
    - それ以外の FX ペア: OANDA API 経由（従来動作）
    暗号資産の場合は従来通りccxt経由でBinanceから取得する。

    Args:
        symbol: 通貨ペア (例: "BTC/USDT", "USD/JPY")
        timeframe: 時間足
        limit: 取得本数（window_size + 余裕分）
        exchange_id: 取引所ID（"saxo_sim", "saxo", "oanda_demo", "oanda", "binance" 等）
    Returns:
        list of dict: ローソク足データ
    """
    if _is_fx_symbol(symbol):
        if exchange_id.startswith("saxo"):
            # Saxo Bank 経由でOHLCV取得
            from src.trading.saxo_client import SaxoClient
            try:
                client = SaxoClient(exchange_id)
            except ValueError:
                # saxo が失敗した場合は saxo_sim を試す
                client = SaxoClient("saxo_sim")
            return client.fetch_ohlcv(symbol, timeframe, limit)
        else:
            # FX通貨ペア: OANDA APIから取得（従来動作）
            from src.trading.oanda_client import OandaClient
            # デモ/本番どちらのトークンでもOHLCV取得は同じ
            oanda_exchange_id = "oanda_demo"
            try:
                client = OandaClient(oanda_exchange_id)
            except ValueError:
                # トークン未設定の場合は oanda を試す
                client = OandaClient("oanda")
            return client.fetch_ohlcv(symbol, timeframe, limit)

    # 暗号資産: ccxt経由（従来通り）
    exchange_class = getattr(ccxt, exchange_id)
    exchange = exchange_class({"enableRateLimit": True})

    ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)

    candles = []
    for row in ohlcv:
        candles.append({
            "timestamp": row[0],
            "datetime": datetime.fromtimestamp(row[0] / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "open": row[1],
            "high": row[2],
            "low": row[3],
            "close": row[4],
            "volume": row[5],
        })

    return candles


def scan_symbol(symbol, config, model=None, dry_run=False,
                strategy=None, candles=None):
    """
    1通貨・1戦略のシグナルスキャンを実行する。

    Args:
        symbol: 通貨ペア (例: "BTC/USDT")
        config: strategy_config 全体
        model: Gemini モデルインスタンス（共有用）
        dry_run: True なら AI判定をスキップ
        strategy: 戦略設定dict（None なら旧方式で自動取得）
        candles: 事前取得済みのローソク足データ（None なら取得する）
    Returns:
        dict: スキャン結果
    """
    # 戦略設定の取得
    if strategy:
        pattern = strategy["pattern"]
        window_size = strategy["window_size"]
        take_profit = strategy["take_profit"]
        stop_loss = strategy["stop_loss"]
        hold_bars = strategy["hold_bars"]
        strategy_id = strategy["id"]
        uses_trend_filter = strategy.get("trend_filter", False)
        # bull trap ガード（BTC限定・他通貨は0=無効のまま後方互換）
        reentry_confirm_days = strategy.get("reentry_confirm_days", 0)
    else:
        # 旧互換: config から直接読み込み
        safe_symbol = symbol.replace("/", "-")
        currency_config = config["currencies"].get(safe_symbol, {})
        default_config = config["default"]
        pattern = currency_config.get("pattern", default_config["pattern"])
        window_size = currency_config.get("window_size", default_config["window_size"])
        take_profit = currency_config.get("take_profit")
        stop_loss = currency_config.get("stop_loss")
        hold_bars = currency_config.get("hold_bars", default_config["hold_bars"])
        strategy_id = pattern
        uses_trend_filter = True
        reentry_confirm_days = 0  # 旧互換: bull trap ガード無効

    print(f"\n{'='*50}")
    print(f"  Scanning: {symbol} [{strategy_id}]")
    print(f"  Pattern: {pattern} | Window: {window_size} | Hold: {hold_bars}")
    print(f"  TP: {f'{take_profit*100}%' if take_profit else 'None'} | SL: {f'{stop_loss*100}%' if stop_loss else 'None'}")
    print(f"{'='*50}")

    # 1. データ取得（事前取得済みでなければ取得）
    if candles is None:
        filter_config = config.get("trend_filter", {})
        slow_period = filter_config.get("slow_period", 200) if filter_config.get("enabled") else 0
        fetch_limit = max(window_size + 10, slow_period + 10)
        print(f"  Fetching latest {fetch_limit} candles...")
        try:
            candles = fetch_latest_candles(symbol, timeframe="1d", limit=fetch_limit)
        except Exception as e:
            print(f"  ERROR: Failed to fetch data: {e}")
            return {
                "symbol": symbol,
                "strategy_id": strategy_id,
                "signal": False,
                "error": str(e),
                "timestamp": datetime.now(JST).isoformat(),
            }

    latest_candles = candles[-window_size:]
    latest_price = latest_candles[-1]["close"]
    latest_datetime = latest_candles[-1]["datetime"]

    print(f"  Latest: {latest_datetime} | Price: {latest_price:,.2f}")

    # 2. トレンドフィルター（direction 別）
    filter_config = config.get("trend_filter", {})
    direction = strategy.get("direction", "long") if strategy else "long"

    if uses_trend_filter:
        if direction == "short":
            from src.signal.trend_filter import check_short_trend_filter
            filtered = check_short_trend_filter(candles, filter_config, strategy_uses_filter=True)
            filter_log = f"[SHORT_FILTERED] Uptrend detected"
        else:
            filtered = check_trend_filter(candles, filter_config,
                                          reentry_confirm_days=reentry_confirm_days)
            filter_log = f"[FILTERED] Downtrend detected"

        if filtered:
            print(f"  {filter_log} (SMA{filter_config.get('fast_period', 50)} vs SMA{filter_config.get('slow_period', 200)}). Skipping.")
            return {
                "symbol": symbol,
                "strategy_id": strategy_id,
                "direction": direction,
                "signal": False,
                "filtered_by": "trend_filter",
                "latest_price": latest_price,
                "latest_datetime": latest_datetime,
                "timestamp": datetime.now(JST).isoformat(),
            }

    if dry_run:
        print(f"  [DRY RUN] Skipping AI judgment")
        return {
            "symbol": symbol,
            "strategy_id": strategy_id,
            "direction": direction,
            "signal": None,
            "latest_price": latest_price,
            "latest_datetime": latest_datetime,
            "candles_count": len(candles),
            "dry_run": True,
            "timestamp": datetime.now(JST).isoformat(),
        }

    # 3. チャート画像生成（一時ファイル）
    print(f"  Generating chart image...")
    chart_img = draw_candlestick_chart(latest_candles, size=512)

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        chart_path = tmp.name
        chart_img.save(chart_path)

    # 4. AI判定
    print(f"  Running AI judgment ({pattern})...")
    try:
        result = judge_chart_image(chart_path, pattern_name=pattern, model=model)
        detected = result["detected"] == 1
    except Exception as e:
        print(f"  ERROR: AI judgment failed: {e}")
        detected = False
        result = {"detected": 0, "raw_response": f"ERROR: {e}"}
    finally:
        os.unlink(chart_path)

    # 5. 結果
    signal_data = {
        "symbol": symbol,
        "strategy_id": strategy_id,
        "direction": direction,
        "signal": detected,
        "pattern": pattern,
        "latest_price": latest_price,
        "latest_datetime": latest_datetime,
        "ai_response": result.get("raw_response", ""),
        "strategy": {
            "take_profit": take_profit,
            "stop_loss": stop_loss,
            "hold_bars": hold_bars,
        },
        "timestamp": datetime.now(JST).isoformat(),
    }

    if detected:
        direction_label = "[SHORT]" if direction == "short" else "[LONG]"
        print(f"\n  >>> SIGNAL DETECTED! {direction_label} [{strategy_id}] <<<")
        print(f"  Entry Price: {latest_price:,.2f}")
        if direction == "short":
            if stop_loss:
                sl_price = latest_price * (1 + stop_loss)  # ショートは上昇でSL
                print(f"  Stop Loss: {sl_price:,.2f} ({stop_loss*100}%)")
            if take_profit:
                tp_price = latest_price * (1 - take_profit)  # ショートは下落でTP
                print(f"  Take Profit: {tp_price:,.2f} ({take_profit*100}%)")
        else:
            if stop_loss:
                sl_price = latest_price * (1 - stop_loss)
                print(f"  Stop Loss: {sl_price:,.2f} ({stop_loss*100}%)")
            if take_profit:
                tp_price = latest_price * (1 + take_profit)
                print(f"  Take Profit: {tp_price:,.2f} ({take_profit*100}%)")
        print(f"  Hold Period: {hold_bars} bars")
    else:
        print(f"  No signal detected.")

    return signal_data


def scan_symbol_multi(symbol, config, model=None, dry_run=False):
    """
    1通貨に対して複数戦略をスキャンする。

    ローソク足データは1回だけ取得し、全戦略で共有する。

    Args:
        symbol: 通貨ペア
        config: strategy_config 全体
        model: Gemini モデルインスタンス
        dry_run: True なら AI判定をスキップ
    Returns:
        list of dict: 各戦略のスキャン結果
    """
    strategies = get_currency_strategies(config, symbol)

    # 全戦略の最大必要本数を計算してデータを1回だけ取得
    max_window = max(s["window_size"] for s in strategies)
    filter_config = config.get("trend_filter", {})
    slow_period = filter_config.get("slow_period", 200) if filter_config.get("enabled") else 0
    fetch_limit = max(max_window + 10, slow_period + 10)

    print(f"\n  Fetching latest {fetch_limit} candles for {symbol}...")
    try:
        candles = fetch_latest_candles(symbol, timeframe="1d", limit=fetch_limit)
    except Exception as e:
        print(f"  ERROR: Failed to fetch data for {symbol}: {e}")
        return [{
            "symbol": symbol,
            "strategy_id": s["id"],
            "signal": False,
            "error": str(e),
            "timestamp": datetime.now(JST).isoformat(),
        } for s in strategies]

    results = []
    for strategy in strategies:
        result = scan_symbol(
            symbol, config, model=model, dry_run=dry_run,
            strategy=strategy, candles=candles,
        )
        results.append(result)

    return results


def run_scan(symbols=None, dry_run=False, save_log=True):
    """
    全通貨のスキャンを実行する。

    Args:
        symbols: スキャン対象の通貨ペアリスト（None なら全通貨）
        dry_run: True なら AI判定をスキップ
        save_log: True ならスキャン結果をJSONで保存
    Returns:
        list of dict: 全通貨のスキャン結果
    """
    config = load_strategy_config()

    if symbols is None:
        symbols = [s.replace("-", "/") for s in config["currencies"].keys()]

    print(f"{'#'*60}")
    print(f"  AI Trade Signal Scanner")
    print(f"  Time: {datetime.now(JST).strftime('%Y-%m-%d %H:%M:%S JST')}")
    print(f"  Targets: {', '.join(symbols)}")
    print(f"  Mode: {'DRY RUN' if dry_run else 'LIVE SCAN'}")
    print(f"{'#'*60}")

    # Geminiモデルを共有（レート制限対策）
    model = None
    if not dry_run:
        print("\nInitializing Gemini AI...")
        model = setup_gemini()

    results = []
    signals_found = []

    for symbol in symbols:
        symbol_results = scan_symbol_multi(symbol, config, model=model, dry_run=dry_run)
        results.extend(symbol_results)

        for r in symbol_results:
            if r.get("signal"):
                signals_found.append(r)

    # サマリー
    print(f"\n{'#'*60}")
    print(f"  SCAN COMPLETE")
    print(f"{'#'*60}")
    print(f"  Scanned: {len(results)} strategy scans across {len(symbols)} currencies")
    print(f"  Signals: {len(signals_found)}")

    if signals_found:
        print(f"\n  Active Signals:")
        for s in signals_found:
            tp = s["strategy"]["take_profit"]
            sl = s["strategy"]["stop_loss"]
            print(f"    {s['symbol']} [{s['strategy_id']}]: {s.get('direction', 'long').upper()} @ {s['latest_price']:,.2f}")
            print(f"      SL: {sl*100 if sl else '-'}% | TP: {tp*100 if tp else '-'}% | Hold: {s['strategy']['hold_bars']} bars")
    else:
        print(f"\n  No signals at this time.")

    # ログ保存
    if save_log:
        os.makedirs(SIGNAL_LOG_DIR, exist_ok=True)
        timestamp = datetime.now(JST).strftime("%Y%m%d_%H%M%S")
        log_path = os.path.join(SIGNAL_LOG_DIR, f"scan_{timestamp}.json")
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump({
                "scan_time": datetime.now(JST).isoformat(),
                "mode": "dry_run" if dry_run else "live",
                "results": results,
                "signals_count": len(signals_found),
            }, f, indent=2, ensure_ascii=False)
        print(f"\n  Log saved: {log_path}")

    return results


def main():
    parser = argparse.ArgumentParser(description="AI Trade Signal Scanner")
    parser.add_argument(
        "--symbols", nargs="+", default=None,
        help="Trading pairs to scan (e.g., BTC/USDT ETH/USDT). Default: all 4 currencies"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Fetch data only, skip AI judgment"
    )
    parser.add_argument(
        "--no-log", action="store_true",
        help="Don't save scan log to file"
    )
    args = parser.parse_args()

    run_scan(
        symbols=args.symbols,
        dry_run=args.dry_run,
        save_log=not args.no_log,
    )


if __name__ == "__main__":
    main()
