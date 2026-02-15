"""自動売買エグゼキューター - シグナルに基づいて発注"""

import logging
from datetime import datetime, timezone

from fx_trader.config import settings
from fx_trader.data_fetcher.oanda_client import OandaClient
from fx_trader.model.predictor import ModelPredictor
from fx_trader.storage.repository import Repository
from fx_trader.trading.risk_manager import RiskManager

logger = logging.getLogger(__name__)


class TradeExecutor:
    """売買シグナルを受けて実際に注文を執行"""

    def __init__(
        self,
        model_name: str,
        repo: Repository = None,
        client: OandaClient = None,
        dry_run: bool = True,
    ):
        self.repo = repo or Repository()
        self.client = client or OandaClient()
        self.predictor = ModelPredictor(model_name, self.repo)
        self.risk_manager = RiskManager(self.repo)
        self.dry_run = dry_run  # True: 注文を出さず、ログのみ

    def execute_signals(
        self,
        instruments: list[str] = None,
        granularity: str = "H1",
        threshold: float = 0.55,
    ) -> list[dict]:
        """全通貨ペアのシグナルを評価して発注

        Returns:
            list of execution results
        """
        targets = instruments or settings.DEFAULT_INSTRUMENTS
        results = []

        for instrument in targets:
            result = self._process_instrument(instrument, granularity, threshold)
            results.append(result)

        return results

    def _process_instrument(self, instrument: str, granularity: str, threshold: float) -> dict:
        """1通貨ペアのシグナル評価→発注"""
        signal = self.predictor.predict_signal(instrument, granularity, threshold)
        result = {"instrument": instrument, "signal": signal, "action": "none", "trade": None}

        if signal["signal_type"] == "hold":
            logger.info("[%s] Signal: HOLD (prob_up=%.3f)", instrument, signal["prob_up"])
            return result

        # リスクチェック
        can_trade, reason = self.risk_manager.can_open_trade(instrument)
        if not can_trade:
            logger.warning("[%s] Cannot open trade: %s", instrument, reason)
            result["action"] = "blocked"
            result["reason"] = reason
            return result

        # 口座残高取得 → ポジションサイズ計算
        try:
            if self.dry_run:
                balance = settings.BACKTEST_INITIAL_BALANCE
            else:
                balance = self.client.get_account_balance()
        except Exception as e:
            logger.error("Failed to get account balance: %s", e)
            return result

        units = self.risk_manager.calculate_position_size(
            balance=balance,
            stop_loss_pips=settings.DEFAULT_STOP_LOSS_PIPS,
            instrument=instrument,
        )

        if units <= 0:
            logger.warning("[%s] Calculated units is 0, skipping", instrument)
            return result

        # 売りの場合はunitsを負にする
        if signal["signal_type"] == "sell":
            units = -units

        # 現在価格取得
        try:
            if self.dry_run:
                candles = self.repo.get_candles(instrument, granularity, limit=1)
                if candles.empty:
                    logger.warning("[%s] No candle data available", instrument)
                    return result
                entry_price = candles["close"].iloc[-1]
            else:
                price_info = self.client.get_current_price(instrument)
                entry_price = price_info["ask"] if signal["signal_type"] == "buy" else price_info["bid"]
        except Exception as e:
            logger.error("Failed to get price for %s: %s", instrument, e)
            return result

        # SL/TP計算
        stop_loss = self.risk_manager.calculate_stop_loss(entry_price, signal["signal_type"], instrument)
        take_profit = self.risk_manager.calculate_take_profit(entry_price, signal["signal_type"], instrument)

        now = datetime.now(timezone.utc).isoformat()

        if self.dry_run:
            logger.info(
                "[DRY RUN] %s %s %d units @ %.5f  SL=%.5f  TP=%.5f  (confidence=%.3f)",
                signal["signal_type"].upper(), instrument, abs(units),
                entry_price, stop_loss, take_profit, signal["confidence"],
            )
            trade_record = {
                "trade_id": f"dry_{instrument}_{now}",
                "instrument": instrument,
                "side": signal["signal_type"],
                "units": abs(units),
                "entry_price": entry_price,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "entry_time": now,
                "status": "open",
                "signal_id": None,
                "notes": f"dry_run, confidence={signal['confidence']:.3f}",
            }
        else:
            # 実際に発注
            try:
                order_result = self.client.create_market_order(
                    instrument=instrument,
                    units=units,
                    stop_loss_price=stop_loss,
                    take_profit_price=take_profit,
                )

                fill = order_result.get("orderFillTransaction", {})
                trade_id = fill.get("tradeOpened", {}).get("tradeID", "unknown")
                fill_price = float(fill.get("price", entry_price))

                logger.info(
                    "[LIVE] %s %s %d units @ %.5f (trade_id=%s)",
                    signal["signal_type"].upper(), instrument, abs(units), fill_price, trade_id,
                )

                trade_record = {
                    "trade_id": trade_id,
                    "instrument": instrument,
                    "side": signal["signal_type"],
                    "units": abs(units),
                    "entry_price": fill_price,
                    "stop_loss": stop_loss,
                    "take_profit": take_profit,
                    "entry_time": now,
                    "status": "open",
                    "signal_id": None,
                    "notes": f"confidence={signal['confidence']:.3f}",
                }
            except Exception as e:
                logger.error("Order failed for %s: %s", instrument, e)
                result["action"] = "error"
                result["error"] = str(e)
                return result

        # シグナルをDB保存
        signal_id = self.repo.upsert_signal({
            "instrument": instrument,
            "granularity": granularity,
            "timestamp": now,
            "signal_type": signal["signal_type"],
            "confidence": signal["confidence"],
            "model_name": signal["model_name"],
        })
        trade_record["signal_id"] = signal_id

        # 取引記録をDB保存
        self.repo.insert_trade(trade_record)

        result["action"] = "executed"
        result["trade"] = trade_record
        return result
