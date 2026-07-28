"""
ポジション管理

建玉・決済の追跡、SL/TP/保有期間の監視を行う。
状態はJSONファイルに永続化し、再起動後も復帰可能。
"""
import os
import json
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))
from enum import Enum

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
POSITIONS_FILE = os.path.join(PROJECT_ROOT, "data/positions.json")
TRADE_HISTORY_FILE = os.path.join(PROJECT_ROOT, "data/trade_history.json")


class PositionStatus(str, Enum):
    OPEN = "open"
    CLOSED_TP = "closed_tp"
    CLOSED_SL = "closed_sl"
    CLOSED_HOLD = "closed_hold"
    CLOSED_MANUAL = "closed_manual"
    ERROR = "error"


class PositionManager:
    """ポジションの状態管理と永続化"""

    def __init__(self, positions_file=None, history_file=None):
        self.positions_file = positions_file or POSITIONS_FILE
        self.history_file = history_file or TRADE_HISTORY_FILE
        self.positions = self._load_positions()

    def _load_positions(self):
        """ファイルからポジションを読み込む"""
        if os.path.exists(self.positions_file):
            with open(self.positions_file, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _save_positions(self):
        """ポジションをファイルに保存する"""
        os.makedirs(os.path.dirname(self.positions_file), exist_ok=True)
        with open(self.positions_file, "w", encoding="utf-8") as f:
            json.dump(self.positions, f, indent=2, ensure_ascii=False)

    def _append_history(self, trade):
        """トレード履歴に追記する"""
        os.makedirs(os.path.dirname(self.history_file), exist_ok=True)
        history = []
        if os.path.exists(self.history_file):
            with open(self.history_file, "r", encoding="utf-8") as f:
                history = json.load(f)
        history.append(trade)
        with open(self.history_file, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2, ensure_ascii=False)

    def _now(self):
        """現在時刻を返す。テスト時に差し替えやすいようメソッド化する。"""
        return datetime.now(JST)

    def _parse_opened_at(self, pos):
        opened_at = pos.get("opened_at")
        if not opened_at:
            return None
        try:
            opened = datetime.fromisoformat(opened_at)
        except (TypeError, ValueError):
            return None
        if opened.tzinfo is None:
            opened = opened.replace(tzinfo=JST)
        return opened.astimezone(JST)

    def _elapsed_hold_days(self, pos, now=None):
        """エントリーからの実経過日数（24時間単位）を返す。"""
        opened = self._parse_opened_at(pos)
        if opened is None:
            return pos.get("bars_held", 0)
        now = now or self._now()
        if now.tzinfo is None:
            now = now.replace(tzinfo=JST)
        elapsed = now.astimezone(JST) - opened
        return max(0, elapsed.days)

    def _is_hold_expired(self, pos, now=None):
        """保有期間が実日数で満了しているか判定する。"""
        opened = self._parse_opened_at(pos)
        hold_days = int(pos.get("hold_bars", 0) or 0)
        if opened is None:
            return pos.get("bars_held", 0) >= hold_days
        now = now or self._now()
        if now.tzinfo is None:
            now = now.replace(tzinfo=JST)
        return now.astimezone(JST) >= opened + timedelta(days=hold_days)

    def open_position(self, symbol, entry_price, amount, order_id,
                      stop_loss=None, take_profit=None, hold_bars=20,
                      sl_order_id=None, strategy_id=None, direction="long"):
        """
        新規ポジションを登録する。

        Args:
            symbol: 通貨ペア（またはキー: "BTC/USDT:double_bottom"）
            entry_price: エントリー価格
            amount: 数量
            order_id: エントリー注文ID
            stop_loss: 損切り率（0.04 = 4%）
            take_profit: 利確率（0.04 = 4%）
            hold_bars: 最大保有期間（日足本数）
            sl_order_id: SL注文のID（取引所に設置済みの場合）
            strategy_id: 戦略ID（例: "double_bottom"）
            direction: ポジション方向（"long" または "short"、デフォルト "long"）
        """
        # ポジションキー: "BTC/USDT:double_bottom" 形式
        position_key = f"{symbol}:{strategy_id}" if strategy_id else symbol
        # 取引所操作用のシンボル（:以前の部分）
        trade_symbol = symbol.split(":")[0] if ":" in symbol else symbol

        # SL/TP価格計算: direction によって方向が変わる
        if direction == "short":
            sl_price = round(entry_price * (1 + stop_loss), 10) if stop_loss else None
            tp_price = round(entry_price * (1 - take_profit), 10) if take_profit else None
        else:
            # long（デフォルト）: 既存動作を維持
            sl_price = round(entry_price * (1 - stop_loss), 10) if stop_loss else None
            tp_price = round(entry_price * (1 + take_profit), 10) if take_profit else None

        position = {
            "symbol": trade_symbol,
            "strategy_id": strategy_id,
            "position_key": position_key,
            "status": PositionStatus.OPEN,
            "direction": direction,
            "entry_price": entry_price,
            "amount": amount,
            "order_id": order_id,
            "stop_loss_pct": stop_loss,
            "take_profit_pct": take_profit,
            "stop_loss_price": sl_price,
            "take_profit_price": tp_price,
            "hold_bars": hold_bars,
            "bars_held": 0,
            "sl_order_id": sl_order_id,
            "opened_at": self._now().isoformat(),
            "closed_at": None,
            "exit_price": None,
            "pnl": None,
            "pnl_pct": None,
            "close_reason": None,
        }

        self.positions[position_key] = position
        self._save_positions()
        return position

    def close_position(self, position_key, exit_price, reason, order_id=None):
        """
        ポジションを決済する。

        Args:
            position_key: ポジションキー（例: "BTC/USDT:double_bottom" or "BTC/USDT"）
            exit_price: 決済価格
            reason: 決済理由（PositionStatus）
            order_id: 決済注文ID
        Returns:
            dict: 決済済みポジション情報
        """
        if position_key not in self.positions:
            return None

        pos = self.positions[position_key]
        entry = pos["entry_price"]
        amount = pos["amount"]
        direction = pos.get("direction") or "long"

        if direction == "short":
            pnl = (entry - exit_price) * amount
            pnl_pct = (entry - exit_price) / entry * 100
        else:
            # long（デフォルト）: 既存動作を維持
            pnl = (exit_price - entry) * amount
            pnl_pct = (exit_price - entry) / entry * 100

        pos["status"] = reason
        pos["exit_price"] = exit_price
        pos["exit_order_id"] = order_id
        pos["pnl"] = round(pnl, 4)
        pos["pnl_pct"] = round(pnl_pct, 2)
        pos["close_reason"] = reason
        pos["closed_at"] = self._now().isoformat()

        # 履歴に追記
        self._append_history(pos)

        # アクティブポジションから削除
        del self.positions[position_key]
        self._save_positions()

        return pos

    def increment_bars(self, position_key):
        """保有期間表示を実経過日数で更新する"""
        if position_key in self.positions:
            pos = self.positions[position_key]
            pos["bars_held"] = self._elapsed_hold_days(pos)
            self._save_positions()

    def check_exit_conditions(self, position_key, current_price):
        """
        決済条件をチェックする。

        Args:
            position_key: ポジションキー
            current_price: 現在価格
        Returns:
            (should_exit: bool, reason: str or None)
        """
        if position_key not in self.positions:
            return False, None

        pos = self.positions[position_key]
        direction = pos.get("direction") or "long"

        if direction == "short":
            # ショート: 価格上昇でSL、価格下落でTP
            if pos["stop_loss_price"] and current_price >= pos["stop_loss_price"]:
                return True, PositionStatus.CLOSED_SL
            if pos["take_profit_price"] and current_price <= pos["take_profit_price"]:
                return True, PositionStatus.CLOSED_TP
        else:
            # ロング（デフォルト）: 既存動作を維持
            # SL チェック（自前監視の場合）
            if pos["stop_loss_price"] and current_price <= pos["stop_loss_price"]:
                return True, PositionStatus.CLOSED_SL
            # TP チェック
            if pos["take_profit_price"] and current_price >= pos["take_profit_price"]:
                return True, PositionStatus.CLOSED_TP

        # 保有期間チェック（direction 無関係）
        pos["bars_held"] = self._elapsed_hold_days(pos)
        if self._is_hold_expired(pos):
            return True, PositionStatus.CLOSED_HOLD

        return False, None

    def get_open_positions(self):
        """オープンポジション一覧を返す"""
        return {k: v for k, v in self.positions.items() if v["status"] == PositionStatus.OPEN}

    def has_position(self, position_key):
        """指定キーのポジションがあるか"""
        return position_key in self.positions

    def get_position(self, position_key):
        """指定キーのポジション情報を返す"""
        return self.positions.get(position_key)

    def get_positions_for_symbol(self, symbol):
        """指定通貨の全ポジションを返す（戦略横断）"""
        return {k: v for k, v in self.positions.items()
                if v.get("symbol") == symbol or k == symbol or k.startswith(f"{symbol}:")}

    def get_trade_history(self):
        """トレード履歴を返す"""
        if os.path.exists(self.history_file):
            with open(self.history_file, "r", encoding="utf-8") as f:
                return json.load(f)
        return []

    def summary(self, quote_currency="USDT"):
        """ポジションサマリーを表示する"""
        positions = self.get_open_positions()
        history = self.get_trade_history()
        fmt = ",.0f" if quote_currency == "JPY" else ",.2f"

        print(f"\n{'='*50}")
        print(f"  Position Summary")
        print(f"{'='*50}")
        print(f"  Open positions: {len(positions)}")

        for sym, pos in positions.items():
            sl = f"SL: {pos['stop_loss_price']:{fmt}}" if pos["stop_loss_price"] else "SL: -"
            tp = f"TP: {pos['take_profit_price']:{fmt}}" if pos["take_profit_price"] else "TP: -"
            direction_label = "[SHORT]" if (pos.get("direction") or "long") == "short" else "[LONG]"
            print(f"    {sym} {direction_label}: Entry {pos['entry_price']:{fmt}} | {sl} | {tp} | Day {pos['bars_held']}/{pos['hold_bars']}")

        if history:
            wins = sum(1 for t in history if t.get("pnl", 0) > 0)
            losses = len(history) - wins
            total_pnl = sum(t.get("pnl", 0) for t in history)
            pnl_fmt = ",.0f" if quote_currency == "JPY" else ",.2f"
            print(f"\n  Trade history: {len(history)} trades ({wins}W / {losses}L)")
            print(f"  Total PnL: {total_pnl:+{pnl_fmt}} {quote_currency}")

        print(f"{'='*50}")
