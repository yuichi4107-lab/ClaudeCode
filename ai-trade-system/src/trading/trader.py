"""
自動売買エンジン

シグナルスキャン → 自動発注 → ポジション管理 → 自動決済
をワンストップで実行する。

使い方:
    # 1回のスキャン＆トレードサイクル実行
    python src/trading/trader.py --exchange binance_testnet

    # ドライラン（注文しない）
    python src/trading/trader.py --dry-run

    # ポジション確認のみ
    python src/trading/trader.py --status

    # 常駐デーモン（日次自動実行）
    python src/trading/trader.py --daemon
"""
import os
import sys
import json
import time
import argparse
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, PROJECT_ROOT)
DAILY_SUMMARY_STATE_PATH = os.path.join(PROJECT_ROOT, "data", "last_daily_summary.txt")
WEEKLY_REPORT_STATE_PATH = os.path.join(PROJECT_ROOT, "data", "last_weekly_report.txt")
MONTHLY_REPORT_STATE_PATH = os.path.join(PROJECT_ROOT, "data", "last_monthly_report.txt")

from src.signal.scanner import scan_symbol, scan_symbol_multi, load_strategy_config, get_currency_strategies
from src.trading.exchange import ExchangeClient
from src.trading.oanda_client import OandaClient
from src.trading.saxo_client import SaxoClient
from src.trading.position_manager import PositionManager, PositionStatus
from src.trading.simulation_tracker import SimulationTracker
from src.notification.notifier import (
    Notifier, format_signal_alert, format_entry_alert,
    format_exit_alert, format_daily_summary, format_error_alert,
)

# 1注文あたりの金額（取引所の建て通貨で指定）
DEFAULT_ORDER_AMOUNTS = {
    "USDT": 20,     # Binance: 20 USDT（約3,000円）
    "JPY": 15000,   # Coincheck: 15,000円（BTC最低0.001≒約13,000円）
}

MIN_BASE_ORDER_AMOUNTS = {
    "BTC": 0.001,
}

# FX用: 1注文あたりのunits数（通貨単位）
DEFAULT_FX_ORDER_UNITS = 1000  # 1,000通貨（USD/JPY: 約1,000ドル、レバ25倍で約6,000円証拠金）


def calculate_order_amount(symbol, price, quote_amount):
    """建て通貨金額から注文数量を計算する"""
    amount = quote_amount / price
    # 通貨ごとの精度調整
    if "BTC" in symbol:
        return round(amount, 5)
    elif "ETH" in symbol:
        return round(amount, 4)
    elif "SOL" in symbol:
        return round(amount, 3)
    elif "XRP" in symbol:
        return round(amount, 1)
    return round(amount, 4)


def is_fx_symbol(symbol):
    """FX通貨ペアかどうかを判定する（3文字/3文字の形式）"""
    parts = symbol.replace("-", "/").split("/")
    return len(parts) == 2 and len(parts[0]) == 3 and len(parts[1]) == 3


class AutoTrader:
    """自動売買エンジン"""

    MAX_CONCURRENT_SHORT_POSITIONS = 3   # B-7: 最大同時ショート建玉数
    DAILY_SHORT_LOSS_LIMIT_PCT = -5.0    # B-6: 証拠金の-5%で circuit breaker

    def __init__(self, exchange_id="binance_testnet", order_amount=None, dry_run=False):
        """
        Args:
            exchange_id: 取引所ID
            order_amount: 1注文あたりの金額（建て通貨単位）。None なら自動設定。
            dry_run: True なら注文を送信しない
        """
        self.dry_run = dry_run
        self.exchange_id = exchange_id
        self.config = load_strategy_config()
        self.pm = PositionManager()
        self.sim = SimulationTracker()
        self.notifier = Notifier()

        self.is_fx = exchange_id.startswith("oanda") or exchange_id.startswith("saxo")
        self.is_futures = exchange_id.startswith("binance_futures")

        if not dry_run:
            if exchange_id.startswith("saxo"):
                self.exchange = SaxoClient(exchange_id)
            elif self.is_fx:
                self.exchange = OandaClient(exchange_id)
            elif self.is_futures:
                from src.trading.futures_exchange import FuturesExchangeClient
                self.exchange = FuturesExchangeClient(exchange_id)
            else:
                self.exchange = ExchangeClient(exchange_id)
            self.quote_currency = self.exchange.quote_currency
            print(f"Exchange: {self.exchange}")
        else:
            self.exchange = None
            if self.is_futures:
                from src.trading.futures_exchange import FuturesExchangeClient
                cfg = FuturesExchangeClient.EXCHANGE_CONFIGS.get(exchange_id, {})
                self.quote_currency = cfg.get("quote_currency", "USDT")
            else:
                all_configs = {**ExchangeClient.EXCHANGE_CONFIGS, **OandaClient.CONFIGS, **SaxoClient.CONFIGS}
                cfg = all_configs.get(exchange_id, {})
                self.quote_currency = cfg.get("quote_currency", "JPY" if self.is_fx else "USDT")
            print(f"Mode: DRY RUN (no orders will be placed)")

        # 注文金額の設定
        if order_amount is not None:
            self.order_amount = order_amount
        else:
            self.order_amount = DEFAULT_ORDER_AMOUNTS.get(self.quote_currency, 20)
        print(f"Order amount: {self.order_amount:,.0f} {self.quote_currency}/trade")

        if self.notifier.is_configured():
            print(f"Notifications: {', '.join(self.notifier.channels)}")
        else:
            print(f"Notifications: disabled (set DISCORD_WEBHOOK_URL or LINE tokens in .env)")

    def run_cycle(self):
        """
        1回のトレードサイクルを実行する。

        1. オープンポジションの決済チェック
        2. 新規シグナルスキャン
        3. シグナル検出時 → 自動エントリー
        """
        now = datetime.now(JST)
        print(f"\n{'#'*60}")
        print(f"  Auto Trader - Trade Cycle")
        print(f"  Time: {now.strftime('%Y-%m-%d %H:%M:%S JST')}")
        print(f"  Mode: {'DRY RUN' if self.dry_run else 'LIVE'}")
        print(f"{'#'*60}")

        # Phase 1: オープンポジションの管理
        self._manage_positions()

        # Phase 1.5: 仮想ポジションの日次チェック
        self._manage_sim_positions()

        # Phase 2: 新規シグナルスキャン＆エントリー
        self._scan_and_enter()

        # Phase 3: 日次サマリー送信＆表示
        self._send_daily_summary()
        self.pm.summary(quote_currency=self.quote_currency)
        self.sim.print_status()

        # Phase 4: 週次・月次シミュレーションレポート（毎日曜・毎月1日に自動生成）
        self._check_sim_report()

    def _manage_sim_positions(self):
        """仮想ポジションの日次SL/TP/Holdチェック"""
        if not self.sim.positions:
            return

        print(f"\n  [SIM] Checking {len(self.sim.positions)} virtual position(s)...")

        def get_price(symbol):
            if self.exchange:
                ticker = self.exchange.get_ticker(symbol)
                return ticker["last"]
            # ドライランの場合はBinanceから取得
            from src.signal.scanner import fetch_latest_candles
            candles = fetch_latest_candles(symbol, timeframe="1d", limit=1)
            return candles[-1]["close"]

        self.sim.update_positions(get_price)

    def _manage_positions(self):
        """オープンポジションの決済チェック"""
        open_positions = self.pm.get_open_positions()

        if not open_positions:
            print(f"\n  No open positions to manage.")
            return

        print(f"\n  Checking {len(open_positions)} open position(s)...")

        for position_key, pos in list(open_positions.items()):
            trade_symbol = pos.get("symbol", position_key.split(":")[0])
            strategy_id = pos.get("strategy_id", "")
            display_name = f"{trade_symbol}[{strategy_id}]" if strategy_id else trade_symbol

            # 保有日数を加算
            self.pm.increment_bars(position_key)

            # 現在価格を取得
            if self.exchange:
                try:
                    ticker = self.exchange.get_ticker(trade_symbol)
                    current_price = ticker["last"]
                except Exception as e:
                    print(f"    {display_name}: Failed to get price: {e}")
                    continue
            else:
                # ドライランの場合はスキップ
                print(f"    {display_name}: [DRY RUN] Skip price check")
                continue

            # 決済条件チェック
            should_exit, reason = self.pm.check_exit_conditions(position_key, current_price)

            entry_price = pos["entry_price"]
            direction = pos.get("direction", "long")
            if direction == "short":
                pnl_pct = (entry_price - current_price) / entry_price * 100
            else:
                pnl_pct = (current_price - entry_price) / entry_price * 100
            direction_label = "[SHORT]" if direction == "short" else "[LONG]"
            print(f"    {display_name} {direction_label}: Price {current_price:,.2f} | PnL {pnl_pct:+.2f}% | Day {pos['bars_held']}/{pos['hold_bars']}")

            if should_exit:
                self._close_position(position_key, current_price, reason)

    def _close_position(self, position_key, current_price, reason):
        """ポジションを決済する"""
        pos = self.pm.get_position(position_key)
        if not pos:
            return

        trade_symbol = pos.get("symbol", position_key.split(":")[0])
        strategy_id = pos.get("strategy_id", "")
        display_name = f"{trade_symbol}[{strategy_id}]" if strategy_id else trade_symbol

        reason_label = {
            PositionStatus.CLOSED_SL: "STOP LOSS",
            PositionStatus.CLOSED_TP: "TAKE PROFIT",
            PositionStatus.CLOSED_HOLD: "HOLD EXPIRED",
        }.get(reason, "MANUAL")

        print(f"\n    >>> CLOSING {display_name}: {reason_label} <<<")

        order_id = None
        exit_price = current_price
        direction = pos.get("direction", "long")

        if not self.dry_run and self.exchange:
            try:
                if direction == "short":
                    # ショート決済: close_short (Futures reduceOnly)
                    order = self.exchange.close_short(trade_symbol, pos["amount"])
                    order_id = order["id"]
                    exit_price = order.get("average") or order.get("price") or current_price
                    print(f"    [SHORT] Close order placed: {order_id}")
                else:
                    # ロング決済: SL注文があればキャンセル後に成行売り
                    if pos.get("sl_order_id"):
                        try:
                            self.exchange.cancel_order(pos["sl_order_id"], trade_symbol)
                            print(f"    Cancelled SL order: {pos['sl_order_id']}")
                        except Exception:
                            pass

                    # --- 案B: 売却前に実残高を取得して売却数量を安全に算出 ---
                    # Coincheckの手数料控除等で pos.amount より実残高が少ない場合でも
                    # 「所持金額が足りません」エラーを回避するための安全網。
                    # 全クローズパス（closed_manual/closed_tp/closed_sl/closed_hold）共通。
                    sell_amount = pos["amount"]
                    if hasattr(self.exchange, "fetch_base_balance"):
                        actual_balance = self.exchange.fetch_base_balance(trade_symbol)
                        if actual_balance is not None:
                            safe_amount = min(sell_amount, actual_balance)
                            if safe_amount < sell_amount:
                                print(f"    [案B] sell amount adjusted: pos={sell_amount:.8f} actual={actual_balance:.8f} -> selling={safe_amount:.8f}")
                            else:
                                print(f"    [案B] balance check OK: pos={sell_amount:.8f} actual={actual_balance:.8f}")
                            sell_amount = safe_amount
                        else:
                            print(f"    [案B] balance check skipped (fetch_base_balance failed, using pos.amount)")
                    # --- 案B ここまで ---

                    order = self.exchange.market_sell(trade_symbol, sell_amount)
                    order_id = order["id"]
                    exit_price = order.get("average") or order.get("price") or current_price
                    print(f"    [LONG] Sell order placed: {order_id}")
            except Exception as e:
                print(f"    ERROR: Failed to close position: {e}")
                return
        else:
            direction_label = "[SHORT]" if direction == "short" else "[LONG]"
            action = "buy back (close short)" if direction == "short" else "sell"
            print(f"    [DRY RUN] Would {action} {pos['amount']} {trade_symbol} @ {current_price:,.2f} {direction_label}")

        # ポジション更新
        closed = self.pm.close_position(position_key, exit_price, reason, order_id)
        if closed:
            pnl_fmt = ",.0f" if self.quote_currency == "JPY" else ",.4f"
            print(f"    PnL: {closed['pnl']:+{pnl_fmt}} {self.quote_currency} ({closed['pnl_pct']:+.2f}%)")
            # 決済通知
            self._notify(format_exit_alert(closed, quote_currency=self.quote_currency), "決済通知")

    def _scan_and_enter(self):
        """シグナルスキャンと新規エントリー（マルチ戦略対応）"""
        symbols = [s.replace("-", "/") for s in self.config["currencies"].keys()]

        print(f"\n  Scanning {len(symbols)} currencies for signals...")

        # Geminiモデルを初期化
        from src.ai.gemini_client import setup_gemini
        model = setup_gemini()

        for symbol in symbols:
            # FXモードでは暗号資産シンボルをスキップ、逆も同様
            sym_is_fx = is_fx_symbol(symbol)
            if self.is_fx and not sym_is_fx:
                print(f"\n  Skipping {symbol} (crypto symbol in FX mode)")
                continue
            if not self.is_fx and sym_is_fx:
                print(f"\n  Skipping {symbol} (FX symbol in crypto mode)")
                continue

            # 取引所がサポートしていない通貨はスキップ
            if self.exchange and not self.exchange.is_symbol_supported(symbol):
                print(f"\n  Skipping {symbol} (not supported by {self.exchange.exchange_id})")
                continue

            strategies = get_currency_strategies(self.config, symbol)

            # 戦略ごとにポジション有無をチェック
            scan_strategies = []
            for s in strategies:
                position_key = f"{symbol}:{s['id']}"
                if self.pm.has_position(position_key):
                    print(f"\n  Skipping {symbol}[{s['id']}] (already have position)")
                else:
                    scan_strategies.append(s)

            if not scan_strategies:
                continue

            # ローソク足データを1回だけ取得
            try:
                from src.signal.scanner import fetch_latest_candles
                max_window = max(s["window_size"] for s in scan_strategies)
                filter_config = self.config.get("trend_filter", {})
                slow_period = filter_config.get("slow_period", 200) if filter_config.get("enabled") else 0
                fetch_limit = max(max_window + 10, slow_period + 10)
                candles = fetch_latest_candles(symbol, timeframe="1d", limit=fetch_limit, exchange_id=self.exchange_id)
            except Exception as e:
                msg = format_error_alert(str(e), f"Data fetch failed: {symbol}")
                self._notify(msg, "エラー通知")
                continue

            for strategy in scan_strategies:
                try:
                    result = scan_symbol(
                        symbol, self.config, model=model, dry_run=False,
                        strategy=strategy, candles=candles,
                    )
                except Exception as e:
                    msg = format_error_alert(str(e), f"Signal scan failed: {symbol}[{strategy['id']}]")
                    self._notify(msg, "エラー通知")
                    continue

                if result.get("signal"):
                    # シミュレーション記録（全シグナルを仮想トレードとして記録）
                    sim_price = result["latest_price"]
                    if self.exchange:
                        try:
                            ticker = self.exchange.get_ticker(symbol)
                            sim_price = ticker["last"]
                        except Exception:
                            pass
                    self.sim.record_signal(
                        symbol=symbol,
                        strategy_id=strategy["id"],
                        entry_price=sim_price,
                        stop_loss_pct=result["strategy"].get("stop_loss"),
                        take_profit_pct=result["strategy"].get("take_profit"),
                        hold_bars=result["strategy"]["hold_bars"],
                    )

                    direction = result.get("direction", "long")

                    if direction == "short":
                        # 安全制御: SL と TP のどちらも None の場合のみブロック
                        sl = result["strategy"].get("stop_loss")
                        tp = result["strategy"].get("take_profit")
                        if sl is None and tp is None:
                            print(f"    BLOCKED: {symbol}[{strategy['id']}] has no stop loss or take profit. Skipping short entry.")
                            continue

                        # 最大同時建玉数チェック (B-7)
                        current_shorts = self._count_open_short_positions()
                        if current_shorts >= self.MAX_CONCURRENT_SHORT_POSITIONS:
                            print(f"    BLOCKED: {symbol}[{strategy['id']}] max concurrent short positions ({self.MAX_CONCURRENT_SHORT_POSITIONS}) reached. Skipping.")
                            continue

                        # 日次損失 circuit breaker (B-6)
                        allowed, cb_reason = self._check_daily_short_loss_limit()
                        if not allowed:
                            print(f"    BLOCKED: {symbol}[{strategy['id']}] {cb_reason}. Skipping.")
                            continue

                        # 取引所の実際の価格でシグナル通知を生成
                        alert_data = dict(result)
                        alert_data["latest_price"] = sim_price
                        self._notify(format_signal_alert(alert_data, quote_currency=self.quote_currency), "シグナル検出")
                        self._enter_short_position(symbol, result, strategy_id=strategy["id"])
                    else:
                        # ロング: SLなし戦略はエントリーしない（安全制御）
                        if not result["strategy"].get("stop_loss"):
                            print(f"    BLOCKED: {symbol}[{strategy['id']}] has no stop loss. Skipping entry.")
                            continue

                        # 取引所の実際の価格でシグナル通知を生成
                        alert_data = dict(result)
                        alert_data["latest_price"] = sim_price
                        self._notify(format_signal_alert(alert_data, quote_currency=self.quote_currency), "シグナル検出")
                        self._enter_position(symbol, result, strategy_id=strategy["id"])

    def _enter_position(self, symbol, signal_data, strategy_id=None):
        """シグナル検出時にポジションをオープンする"""
        strategy = signal_data["strategy"]
        sid = strategy_id or signal_data.get("strategy_id", "")
        display_name = f"{symbol}[{sid}]" if sid else symbol

        # 実際の取引所価格を取得（シグナルはBinance/USDTベースのため）
        if self.exchange:
            try:
                ticker = self.exchange.get_ticker(symbol)
                price = ticker["last"]
            except Exception as e:
                print(f"\n    ERROR: Failed to get exchange price for {display_name}: {e}")
                return
        else:
            price = signal_data["latest_price"]

        if self.is_fx:
            # FX: units（通貨単位数）で注文
            amount = DEFAULT_FX_ORDER_UNITS
            print(f"\n    >>> ENTERING {display_name} <<<")
            print(f"    Price: {price:,.3f} | Units: {amount:,} | FX mode")
        else:
            base_currency = symbol.split("/")[0]
            min_base_amount = MIN_BASE_ORDER_AMOUNTS.get(base_currency)
            min_quote_amount = (min_base_amount * price) if min_base_amount else 0
            quote_amount = max(self.order_amount, min_quote_amount)
            if not self.dry_run and self.exchange:
                try:
                    balance = self.exchange.get_balance(self.quote_currency)
                    free = float(balance.get("free", 0) or 0)
                    if free < quote_amount:
                        print(
                            f"    BLOCKED: insufficient {self.quote_currency} balance "
                            f"({free:,.0f} < required {quote_amount:,.0f}) for {display_name}."
                        )
                        return
                except Exception as e:
                    print(f"    [BALANCE] balance check skipped: {e}")

            amount = calculate_order_amount(symbol, price, quote_amount)
            print(f"\n    >>> ENTERING {display_name} <<<")
            print(f"    Price: {price:,.2f} | Amount: {amount} | ~{quote_amount:,.0f} {self.quote_currency}")

        order_id = None
        entry_price = price
        sl_order_id = None

        if not self.dry_run and self.exchange:
            try:
                # 成行買い（Coincheckは quote_amount=JPY金額 で指定）
                order = self.exchange.market_buy(symbol, amount, quote_amount=None if self.is_fx else quote_amount)
                order_id = order["id"]
                entry_price = order.get("average") or order.get("price") or price
                # 実際の約定数量があれば上書き（Coincheckは金額指定のためfilledが正確）
                if order.get("filled"):
                    amount = order["filled"]
                print(f"    Buy order placed: {order_id} @ {entry_price:,.2f}")

                # --- 案A: 買付後に実BTC残高を取得してamountを補正 ---
                # Coincheckの手数料控除で約定数量より実残高が少なくなる場合があるため、
                # fetch_base_balance で実際の残高を取得して positions.json に記録する。
                if hasattr(self.exchange, "fetch_base_balance"):
                    actual_balance = self.exchange.fetch_base_balance(symbol)
                    if actual_balance is not None and actual_balance < amount:
                        print(f"    [案A] amount adjusted: order={amount:.8f} actual={actual_balance:.8f} {symbol.split('/')[0]}")
                        amount = actual_balance
                    elif actual_balance is not None:
                        print(f"    [案A] balance check OK: order={amount:.8f} actual={actual_balance:.8f} {symbol.split('/')[0]}")
                    else:
                        print(f"    [案A] balance check skipped (fetch_base_balance failed, using order amount)")
                # --- 案A ここまで ---

                # SL注文を取引所に設置
                if strategy["stop_loss"]:
                    sl_price = entry_price * (1 - strategy["stop_loss"])
                    sl_order = self.exchange.stop_loss_order(symbol, amount, sl_price)
                    if sl_order:
                        sl_order_id = sl_order["id"]
                        print(f"    SL order placed: {sl_order_id} @ {sl_price:,.2f}")
                    else:
                        print(f"    SL order not supported, using self-monitoring")

            except Exception as e:
                print(f"    ERROR: Failed to place order: {e}")
                return
        else:
            print(f"    [DRY RUN] Would buy {amount} {symbol} @ {price:,.2f}")
            order_id = f"dry_run_{datetime.now(JST).strftime('%Y%m%d%H%M%S')}"

        # ポジション登録
        self.pm.open_position(
            symbol=symbol,
            entry_price=entry_price,
            amount=amount,
            order_id=order_id,
            stop_loss=strategy["stop_loss"],
            take_profit=strategy["take_profit"],
            hold_bars=strategy["hold_bars"],
            sl_order_id=sl_order_id,
            strategy_id=sid,
        )

        sl = strategy["stop_loss"]
        tp = strategy["take_profit"]
        print(f"    Position opened [{sid}]:")
        print(f"      SL: {entry_price * (1 - sl):,.2f} ({sl*100}%)" if sl else "      SL: None")
        print(f"      TP: {entry_price * (1 + tp):,.2f} ({tp*100}%)" if tp else "      TP: None")
        print(f"      Hold: {strategy['hold_bars']} bars")

        # エントリー通知
        self._notify(
            format_entry_alert(symbol, entry_price, amount, order_id, strategy, quote_currency=self.quote_currency),
            "エントリー通知",
        )

    def _enter_short_position(self, symbol, signal_data, strategy_id=None):
        """ショートシグナル検出時にショートポジションをオープンする"""
        strategy = signal_data["strategy"]
        sid = strategy_id or signal_data.get("strategy_id", "")
        display_name = f"{symbol}[{sid}]" if sid else symbol

        # 実際の取引所価格を取得
        if self.exchange:
            try:
                ticker = self.exchange.get_ticker(symbol)
                price = ticker["last"]
            except Exception as e:
                print(f"\n    ERROR: Failed to get exchange price for {display_name}: {e}")
                return
        else:
            price = signal_data["latest_price"]

        amount = calculate_order_amount(symbol, price, self.order_amount)
        print(f"\n    >>> ENTERING SHORT {display_name} <<<")
        print(f"    Price: {price:,.2f} | Amount: {amount} | ~{self.order_amount:,.0f} {self.quote_currency}")

        order_id = None
        entry_price = price

        if not self.dry_run and self.exchange:
            try:
                order = self.exchange.open_short(symbol, amount)
                order_id = order["id"]
                entry_price = order.get("average") or order.get("price") or price
                print(f"    Short order placed: {order_id} @ {entry_price:,.2f}")
            except Exception as e:
                print(f"    ERROR: Failed to place short order: {e}")
                return
        else:
            print(f"    [DRY RUN] Would open short {amount} {symbol} @ {price:,.2f}")
            order_id = f"dry_run_short_{datetime.now(JST).strftime('%Y%m%d%H%M%S')}"

        # ポジション登録 (direction="short")
        self.pm.open_position(
            symbol=symbol,
            entry_price=entry_price,
            amount=amount,
            order_id=order_id,
            stop_loss=strategy["stop_loss"],
            take_profit=strategy["take_profit"],
            hold_bars=strategy["hold_bars"],
            sl_order_id=None,  # Futures は取引所SLなし、自前監視
            strategy_id=sid,
            direction="short",
        )

        sl = strategy["stop_loss"]
        tp = strategy["take_profit"]
        print(f"    Short position opened [{sid}]:")
        print(f"      SL: {entry_price * (1 + sl):,.2f} ({sl*100}%)" if sl else "      SL: None")
        print(f"      TP: {entry_price * (1 - tp):,.2f} ({tp*100}%)" if tp else "      TP: None")
        print(f"      Hold: {strategy['hold_bars']} bars")

        # エントリー通知
        self._notify(
            "[SHORT] " + format_entry_alert(symbol, entry_price, amount, order_id, strategy, quote_currency=self.quote_currency),
            "エントリー通知（ショート）",
        )

    def _count_open_short_positions(self):
        """現在のオープンショートポジション数を返す"""
        open_positions = self.pm.get_open_positions()
        return sum(1 for p in open_positions.values() if p.get("direction") == "short")

    def _check_daily_short_loss_limit(self):
        """当日のショート累計損失が閾値を超えていないか判定する

        Returns:
            (allowed: bool, reason: str)
        """
        history = self.pm.get_trade_history()
        today = datetime.now(JST).date()
        daily_short_pnl_pct = 0.0

        for trade in history:
            if trade.get("direction") != "short":
                continue
            closed_at = trade.get("closed_at", "")
            if not closed_at:
                continue
            try:
                closed_date = datetime.fromisoformat(closed_at).date()
            except Exception:
                continue
            if closed_date == today:
                daily_short_pnl_pct += trade.get("pnl_pct", 0) or 0

        if daily_short_pnl_pct <= self.DAILY_SHORT_LOSS_LIMIT_PCT:
            return False, f"Daily short loss limit hit: {daily_short_pnl_pct:.2f}% <= {self.DAILY_SHORT_LOSS_LIMIT_PCT}%"
        return True, f"Daily short PnL so far: {daily_short_pnl_pct:+.2f}%"

    def _notify(self, message, title=None):
        """通知を送信する（設定済みの場合のみ）"""
        if self.notifier.is_configured():
            self.notifier.send(message, title)

    def _already_sent_periodic_report(self, state_path, period_key, label):
        """定期レポートの重複送信を防ぐ。"""
        try:
            if os.path.exists(state_path):
                with open(state_path, "r", encoding="utf-8") as f:
                    if f.read().strip() == period_key:
                        print(f"  {label} skipped (already sent for {period_key}).")
                        return True
        except Exception as e:
            print(f"  {label} state check skipped: {e}")
        return False

    def _mark_periodic_report_sent(self, state_path, period_key, label):
        """定期レポートの送信済み状態を記録する。"""
        try:
            os.makedirs(os.path.dirname(state_path), exist_ok=True)
            with open(state_path, "w", encoding="utf-8") as f:
                f.write(period_key)
        except Exception as e:
            print(f"  {label} state write failed: {e}")

    def _check_sim_report(self):
        """週次（日曜）・月次（1日）にシミュレーションレポートを自動生成する"""
        now = datetime.now(JST)

        # 週次: 日曜日 (weekday() == 6)
        if now.weekday() == 6:
            week_key = f"{now.isocalendar().year}-W{now.isocalendar().week:02d}"
            if not self._already_sent_periodic_report(
                WEEKLY_REPORT_STATE_PATH, week_key, "Weekly simulation report"
            ):
                print(f"\n  [SIM] Generating weekly report...")
                report = self.sim.generate_report("week")
                text = self.sim.format_report(report)
                print(text)
                self.sim.save_report(report)
                self._notify(text, "週次シミュレーションレポート")
                self._mark_periodic_report_sent(
                    WEEKLY_REPORT_STATE_PATH, week_key, "Weekly simulation report"
                )

        # 月次: 毎月1日
        if now.day == 1:
            month_key = now.strftime("%Y-%m")
            if not self._already_sent_periodic_report(
                MONTHLY_REPORT_STATE_PATH, month_key, "Monthly simulation report"
            ):
                print(f"\n  [SIM] Generating monthly report...")
                report = self.sim.generate_report("month")
                text = self.sim.format_report(report)
                print(text)
                self.sim.save_report(report)
                self._notify(text, "月次シミュレーションレポート")
                self._mark_periodic_report_sent(
                    MONTHLY_REPORT_STATE_PATH, month_key, "Monthly simulation report"
                )

    def _send_daily_summary(self):
        """日次サマリーを通知する"""
        today = datetime.now(JST).strftime("%Y-%m-%d")
        if self._already_sent_periodic_report(
            DAILY_SUMMARY_STATE_PATH, today, "Daily summary notification"
        ):
            return

        positions = self.pm.get_open_positions()
        history = self.pm.get_trade_history()

        balances = None
        if self.exchange:
            try:
                balances = {self.quote_currency: self.exchange.get_balance()}
            except Exception:
                pass

        summary = format_daily_summary(positions, history, balances, quote_currency=self.quote_currency)
        self._notify(summary, "日次レポート")
        self._mark_periodic_report_sent(
            DAILY_SUMMARY_STATE_PATH, today, "Daily summary notification"
        )

    def run_daemon(self, interval_hours=24):
        """
        常駐デーモンモード。指定間隔でトレードサイクルを繰り返す。

        Args:
            interval_hours: 実行間隔（時間）
        """
        print(f"\n  Starting daemon mode (interval: {interval_hours}h)")
        print(f"  Press Ctrl+C to stop.\n")

        while True:
            try:
                self.run_cycle()
            except KeyboardInterrupt:
                print(f"\n  Daemon stopped by user.")
                break
            except Exception as e:
                print(f"\n  ERROR in trade cycle: {e}")
                self._notify(format_error_alert(str(e), "Trade cycle error"), "エラー通知")

            next_run = datetime.now(JST).strftime('%Y-%m-%d %H:%M:%S JST')
            print(f"\n  Next cycle in {interval_hours}h (current: {next_run})")

            try:
                time.sleep(interval_hours * 3600)
            except KeyboardInterrupt:
                print(f"\n  Daemon stopped by user.")
                break

    def show_status(self):
        """現在のポジションとトレード履歴を表示する"""
        self.pm.summary(quote_currency=self.quote_currency)

        # 詳細なオープンポジション
        positions = self.pm.get_open_positions()
        if positions and self.exchange:
            print(f"\n  Current prices:")
            for position_key, pos in positions.items():
                trade_symbol = pos.get("symbol", position_key.split(":")[0])
                strategy_id = pos.get("strategy_id", "")
                display_name = f"{trade_symbol}[{strategy_id}]" if strategy_id else trade_symbol
                try:
                    ticker = self.exchange.get_ticker(trade_symbol)
                    pnl_pct = (ticker["last"] - pos["entry_price"]) / pos["entry_price"] * 100
                    print(f"    {display_name}: {ticker['last']:,.2f} (PnL: {pnl_pct:+.2f}%)")
                except Exception as e:
                    print(f"    {display_name}: Failed to get price: {e}")

        # シミュレーション状況
        self.sim.print_status()
        if self.sim.history:
            report = self.sim.generate_report("week")
            print(self.sim.format_report(report))


def main():
    parser = argparse.ArgumentParser(description="AI Auto Trader")
    parser.add_argument(
        "--exchange", default="binance_testnet",
        choices=["binance_testnet", "binance", "coincheck", "oanda_demo", "oanda", "saxo_sim", "saxo",
                 "binance_futures_testnet", "binance_futures"],
        help="Exchange to use (default: binance_testnet)"
    )
    parser.add_argument(
        "--amount", type=float, default=None,
        help="Order amount per trade in quote currency (default: auto by exchange)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Simulate trades without placing orders"
    )
    parser.add_argument(
        "--daemon", action="store_true",
        help="Run in daemon mode (repeat every 24h)"
    )
    parser.add_argument(
        "--interval", type=float, default=24,
        help="Daemon interval in hours (default: 24)"
    )
    parser.add_argument(
        "--status", action="store_true",
        help="Show current positions and trade history"
    )
    parser.add_argument(
        "--sim-report", choices=["week", "month"],
        help="Generate simulation report (week or month)"
    )
    args = parser.parse_args()

    trader = AutoTrader(
        exchange_id=args.exchange,
        order_amount=args.amount,
        dry_run=args.dry_run,
    )

    if args.sim_report:
        report = trader.sim.generate_report(args.sim_report)
        print(trader.sim.format_report(report))
        trader.sim.save_report(report)
    elif args.status:
        trader.show_status()
    elif args.daemon:
        trader.run_daemon(interval_hours=args.interval)
    else:
        trader.run_cycle()


if __name__ == "__main__":
    main()
