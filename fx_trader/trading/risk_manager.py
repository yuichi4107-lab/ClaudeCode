"""リスク管理 - ポジションサイズ計算・損失制限"""

import logging
from datetime import datetime, timezone

from fx_trader.config import settings
from fx_trader.storage.repository import Repository

logger = logging.getLogger(__name__)


class RiskManager:
    """リスク管理とポジションサイジング"""

    def __init__(self, repo: Repository = None):
        self.repo = repo or Repository()

    def calculate_position_size(
        self,
        balance: float,
        stop_loss_pips: float,
        instrument: str,
        pip_value_per_unit: float = None,
    ) -> int:
        """リスクベースのポジションサイズを計算

        Args:
            balance: 口座残高
            stop_loss_pips: 損切り幅 (pips)
            instrument: 通貨ペア
            pip_value_per_unit: 1ロットあたりの1pipの価値（円）

        Returns:
            取引ロット数 (units)
        """
        risk_amount = balance * (settings.RISK_PER_TRADE_PCT / 100)

        pip_loc = settings.INSTRUMENTS.get(instrument, {}).get("pip_location", -2)
        if pip_value_per_unit is None:
            # JPY通貨ペアは1pipあたり約0.01円/unit
            pip_value_per_unit = 10 ** pip_loc

        if stop_loss_pips <= 0:
            logger.warning("Invalid stop_loss_pips: %s, using default", stop_loss_pips)
            stop_loss_pips = settings.DEFAULT_STOP_LOSS_PIPS

        units = int(risk_amount / (stop_loss_pips * pip_value_per_unit))
        units = min(units, settings.MAX_POSITION_SIZE)

        logger.info(
            "Position size: %d units (balance=%.0f, risk=%.0f, SL=%.1f pips)",
            units, balance, risk_amount, stop_loss_pips,
        )
        return units

    def can_open_trade(self, instrument: str = None) -> tuple[bool, str]:
        """新規ポジションを開けるか判定

        Returns:
            (可否, 理由)
        """
        open_trades = self.repo.get_open_trades(instrument)

        # 最大同時ポジション数
        all_open = self.repo.get_open_trades()
        if len(all_open) >= settings.MAX_OPEN_TRADES:
            return False, f"Maximum open trades reached ({settings.MAX_OPEN_TRADES})"

        # 同一通貨ペアの重複チェック
        if instrument and open_trades:
            return False, f"Already have open trade for {instrument}"

        # 日次損失制限チェック
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        history = self.repo.get_trade_history(from_time=today)
        if not history.empty:
            daily_loss = history["pnl"].sum()
            # account_snapshotsから直近残高取得は簡略化し、settingsの初期資金で代用
            max_loss = settings.BACKTEST_INITIAL_BALANCE * (settings.MAX_DAILY_LOSS_PCT / 100)
            if daily_loss < -max_loss:
                return False, f"Daily loss limit reached ({daily_loss:.0f})"

        return True, "OK"

    def calculate_stop_loss(self, entry_price: float, side: str, instrument: str, atr: float = None) -> float:
        """損切り価格を計算

        Args:
            entry_price: エントリー価格
            side: "buy" or "sell"
            instrument: 通貨ペア
            atr: ATR値（あれば動的SL計算）
        """
        pip_loc = settings.INSTRUMENTS.get(instrument, {}).get("pip_location", -2)
        pip_value = 10 ** pip_loc

        if atr:
            sl_distance = atr * 1.5  # ATRの1.5倍
        else:
            sl_distance = settings.DEFAULT_STOP_LOSS_PIPS * pip_value

        if side == "buy":
            return round(entry_price - sl_distance, abs(pip_loc) + 1)
        else:
            return round(entry_price + sl_distance, abs(pip_loc) + 1)

    def calculate_take_profit(self, entry_price: float, side: str, instrument: str, atr: float = None) -> float:
        """利確価格を計算（リスク:リワード = 1:2）"""
        pip_loc = settings.INSTRUMENTS.get(instrument, {}).get("pip_location", -2)
        pip_value = 10 ** pip_loc

        if atr:
            tp_distance = atr * 3.0  # ATRの3倍 (SLの2倍)
        else:
            tp_distance = settings.DEFAULT_TAKE_PROFIT_PIPS * pip_value

        if side == "buy":
            return round(entry_price + tp_distance, abs(pip_loc) + 1)
        else:
            return round(entry_price - tp_distance, abs(pip_loc) + 1)
