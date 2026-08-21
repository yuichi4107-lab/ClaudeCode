"""
サーキットブレーカー — FX Phase1 フォワードテスト用

portfolio_config.json の CB 設定に基づき、注文を制御する。

CB1: 連敗N回     → 該当戦略を当日停止
CB2: 月次DD N%   → 全戦略を月末まで停止
CB3: 累積DD N%   → 全戦略停止（手動解除のみ）
CB4: 前月マイナス → ロット50%削減

状態管理:
    - メモリ内で管理（再起動時にリセット）
    - 永続化は別フェーズで実装
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# CB4 ロット削減率（50%削減 → modifier=0.5）
CB4_LOT_MODIFIER = 0.5


class CircuitBreaker:
    """
    portfolio_config.json の CB 設定に基づき、注文を制御する。

    CB1: 連敗N回     → 該当戦略を当日停止
    CB2: 月次DD N%   → 全戦略を月末まで停止
    CB3: 累積DD N%   → 全戦略停止（手動解除のみ）
    CB4: 前月マイナス → ロット50%削減

    Args:
        cb_config: get_circuit_breaker_config() が返す CB 設定 dict
    """

    def __init__(self, cb_config: Dict[str, Any]):
        """
        CircuitBreaker を初期化する。

        Args:
            cb_config: サーキットブレーカー設定 dict。
                       get_circuit_breaker_config() の返り値を想定。
                       必要キー:
                           consecutive_loss_limit         (int,   デフォルト5)
                           monthly_dd_limit_pct           (float, デフォルト10.0)
                           cumulative_dd_limit_pct        (float, デフォルト25.0)
                           end_of_month_reduction_threshold_pct (float, デフォルト0)
        """
        self.consecutive_loss_limit: int = int(
            cb_config.get("consecutive_loss_limit", 5)
        )
        self.monthly_dd_limit_pct: float = float(
            cb_config.get("monthly_dd_limit_pct", 10.0)
        )
        self.cumulative_dd_limit_pct: float = float(
            cb_config.get("cumulative_dd_limit_pct", 25.0)
        )
        self.end_of_month_reduction_threshold_pct: float = float(
            cb_config.get("end_of_month_reduction_threshold_pct", 0)
        )

        # ─── 状態: 戦略別 ───
        # {strategy_key: {"consecutive_losses": int, "cb1_stopped_date": "YYYYMMDD"|None}}
        # strategy_key = f"{strategy_id}:{symbol}:{timeframe}" で一意に識別
        self._strategy_states: Dict[str, Dict[str, Any]] = {}

        # ─── 状態: 月次 ───
        self._monthly_pnl_pct: float = 0.0      # 月初からの損益 (%)
        self._monthly_start_balance: Optional[float] = None  # 月初残高（円）
        self._cb2_stopped: bool = False          # CB2 発動中フラグ
        self._cb2_stop_month: Optional[str] = None  # CB2 停止中の月 "YYYYMM"

        # CB4: 月次損益がマイナスかどうかで判定（翌月にリセット）
        self._cb4_active: bool = False           # CB4 発動中フラグ
        self._cb4_month: Optional[str] = None   # CB4 判定月 "YYYYMM"

        # ─── 状態: 累積 ───
        self._cumulative_pnl_pct: float = 0.0   # 運用開始からの累積損益 (%)
        self._peak_balance: Optional[float] = None  # ピーク残高（高値）
        self._initial_balance: Optional[float] = None  # 初期残高
        self._cb3_stopped: bool = False          # CB3 発動中フラグ（手動解除のみ）

        logger.info(
            "CircuitBreaker 初期化: CB1=%d連敗, CB2=月次DD%.1f%%, "
            "CB3=累積DD%.1f%%, CB4=月末縮小閾値%.1f%%",
            self.consecutive_loss_limit,
            self.monthly_dd_limit_pct,
            self.cumulative_dd_limit_pct,
            self.end_of_month_reduction_threshold_pct,
        )

    # ─────────────────────────────────────────────
    # パブリックメソッド
    # ─────────────────────────────────────────────

    def check(
        self,
        strategy_id: str,
        signal: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        注文実行の可否をチェックする（優先度: CB3 > CB2 > CB4 > CB1）。

        Args:
            strategy_id: 戦略ID（例: "mtf_confluence"）
            signal: シグナル dict。少なくとも "symbol" と "timeframe" を含む。

        Returns:
            {
                "allowed": bool,
                "reason": str,
                "lot_modifier": float,   # 1.0 = 通常, 0.5 = CB4発動中
                "cb_status": {
                    "cb1": bool,  # CB1 発動中（この戦略）
                    "cb2": bool,  # CB2 発動中
                    "cb3": bool,  # CB3 発動中
                    "cb4_lot_modifier": float,
                }
            }
        """
        symbol = signal.get("symbol", "")
        timeframe = signal.get("timeframe", "")
        strategy_key = self._make_strategy_key(strategy_id, symbol, timeframe)
        today_str = self._today_str()

        lot_modifier = 1.0

        # CB3 チェック（最優先: 累積DD超過 → 手動解除のみ）
        if self._cb3_stopped:
            logger.warning(
                "[CB3] check() でブロック: %s %s %s - 累積DD閾値超過中",
                strategy_id, symbol, timeframe,
            )
            return {
                "allowed": False,
                "reason": (
                    f"CB3発動: 累積DD閾値 {self.cumulative_dd_limit_pct:.1f}% 超過。"
                    "手動解除が必要です。"
                ),
                "lot_modifier": 0.0,
                "cb_status": self._build_cb_status(
                    cb1=self._is_cb1_active(strategy_key, today_str),
                ),
            }

        # CB2 チェック（月次DD超過 → 月末まで全停止）
        if self._cb2_stopped:
            logger.warning(
                "[CB2] check() でブロック: %s %s %s - 月次DD閾値超過中 (%s)",
                strategy_id, symbol, timeframe, self._cb2_stop_month,
            )
            return {
                "allowed": False,
                "reason": (
                    f"CB2発動: 月次DD閾値 {self.monthly_dd_limit_pct:.1f}% 超過。"
                    f"月末まで全戦略停止中（{self._cb2_stop_month}）。"
                ),
                "lot_modifier": 0.0,
                "cb_status": self._build_cb_status(
                    cb1=self._is_cb1_active(strategy_key, today_str),
                ),
            }

        # CB4 チェック（ロット削減）
        if self._cb4_active:
            lot_modifier = CB4_LOT_MODIFIER

        # CB1 チェック（連敗N回 → 当日停止）
        if self._is_cb1_active(strategy_key, today_str):
            return {
                "allowed": False,
                "reason": (
                    f"CB1発動: {strategy_id} ({symbol} {timeframe}) が "
                    f"連続 {self.consecutive_loss_limit} 回損失。当日停止中。"
                ),
                "lot_modifier": 0.0,
                "cb_status": self._build_cb_status(cb1=True),
            }

        return {
            "allowed": True,
            "reason": "OK",
            "lot_modifier": lot_modifier,
            "cb_status": self._build_cb_status(cb1=False),
        }

    def record_trade_result(
        self,
        strategy_id: str,
        pnl_pct: float,
        symbol: str = "",
        timeframe: str = "",
        current_balance: Optional[float] = None,
    ) -> None:
        """
        トレード結果を記録し、CB 状態を更新する。

        Args:
            strategy_id:      戦略ID
            pnl_pct:          損益率（%。正=利益, 負=損失）
            symbol:           通貨ペア（CB1の戦略識別に使用）
            timeframe:        時間足（CB1の戦略識別に使用）
            current_balance:  現在の口座残高（円）。CB2/CB3の計算に使用。
                              None の場合は損益率のみで累計計算する。
        """
        today_str = self._today_str()
        strategy_key = self._make_strategy_key(strategy_id, symbol, timeframe)

        # ─── CB1: 連敗カウント更新 ───
        state = self._get_strategy_state(strategy_key)
        if pnl_pct < 0:
            state["consecutive_losses"] = state.get("consecutive_losses", 0) + 1
            losses = state["consecutive_losses"]
            logger.debug(
                "[CB1] %s 連敗カウント: %d / %d",
                strategy_key, losses, self.consecutive_loss_limit,
            )
            if losses >= self.consecutive_loss_limit:
                state["cb1_stopped_date"] = today_str
                logger.warning(
                    "[CB1] 発動: %s が %d 連敗。本日(%s)停止。",
                    strategy_key, losses, today_str,
                )
        else:
            # 勝ちトレードで連敗リセット
            prev = state.get("consecutive_losses", 0)
            state["consecutive_losses"] = 0
            if prev > 0:
                logger.debug("[CB1] %s 連敗リセット（%d → 0）", strategy_key, prev)

        self._strategy_states[strategy_key] = state

        # ─── 月次損益・CB2/CB4 更新 ───
        self._monthly_pnl_pct += pnl_pct

        # 月次DD = monthly_pnl_pct が負になったときの絶対値
        monthly_dd = abs(min(self._monthly_pnl_pct, 0.0))
        if not self._cb2_stopped and monthly_dd >= self.monthly_dd_limit_pct:
            current_month = self._current_month_str()
            self._cb2_stopped = True
            self._cb2_stop_month = current_month
            logger.warning(
                "[CB2] 発動: 月次DD %.2f%% が閾値 %.1f%% を超過。"
                "月末まで全戦略停止（%s）。",
                monthly_dd, self.monthly_dd_limit_pct, current_month,
            )

        # ─── 累積損益・CB3 更新 ───
        self._cumulative_pnl_pct += pnl_pct

        if current_balance is not None:
            # ピーク残高の更新
            if self._initial_balance is None:
                self._initial_balance = current_balance
            if self._peak_balance is None or current_balance > self._peak_balance:
                self._peak_balance = current_balance

            # 累積DDをピーク残高から計算
            if self._peak_balance and self._peak_balance > 0:
                cumulative_dd_from_peak = (
                    (self._peak_balance - current_balance) / self._peak_balance * 100
                )
            else:
                cumulative_dd_from_peak = 0.0
        else:
            # current_balance 未指定 → 累積損益率の累計で近似
            cumulative_dd_from_peak = abs(min(self._cumulative_pnl_pct, 0.0))

        if not self._cb3_stopped and cumulative_dd_from_peak >= self.cumulative_dd_limit_pct:
            self._cb3_stopped = True
            logger.critical(
                "[CB3] 発動: 累積DD %.2f%% が閾値 %.1f%% を超過。"
                "全戦略即時停止。手動解除が必要。",
                cumulative_dd_from_peak, self.cumulative_dd_limit_pct,
            )

        logger.debug(
            "record_trade_result: %s pnl_pct=%.4f%%, "
            "monthly_pnl=%.4f%%, cumulative_pnl=%.4f%%",
            strategy_key, pnl_pct, self._monthly_pnl_pct, self._cumulative_pnl_pct,
        )

    def get_status(self) -> Dict[str, Any]:
        """
        全 CB の現在状態を返す。

        Returns:
            {
                "cb1": {
                    "<strategy_key>": {
                        "consecutive_losses": int,
                        "cb1_stopped_date": str | None,
                    }
                },
                "cb2": {
                    "stopped": bool,
                    "monthly_pnl_pct": float,
                    "stop_month": str | None,
                },
                "cb3": {
                    "stopped": bool,
                    "cumulative_pnl_pct": float,
                },
                "cb4": {
                    "active": bool,
                    "lot_modifier": float,
                },
            }
        """
        return {
            "cb1": {
                key: dict(state)
                for key, state in self._strategy_states.items()
            },
            "cb2": {
                "stopped": self._cb2_stopped,
                "monthly_pnl_pct": self._monthly_pnl_pct,
                "stop_month": self._cb2_stop_month,
            },
            "cb3": {
                "stopped": self._cb3_stopped,
                "cumulative_pnl_pct": self._cumulative_pnl_pct,
            },
            "cb4": {
                "active": self._cb4_active,
                "lot_modifier": CB4_LOT_MODIFIER if self._cb4_active else 1.0,
            },
        }

    def reset_monthly(self, current_balance: Optional[float] = None) -> None:
        """
        月初に CB2 / CB4 の月次状態をリセットする。

        CB4 の判定ロジック:
            前月の月次損益がマイナス（end_of_month_reduction_threshold_pct 以下）
            であれば翌月を CB4 発動状態にする。

        Args:
            current_balance: 現在の口座残高。CB4 の月初残高としてセットする。
        """
        current_month = self._current_month_str()
        prev_monthly_pnl = self._monthly_pnl_pct

        # CB4 判定: 前月がマイナスなら翌月ロット削減
        threshold = self.end_of_month_reduction_threshold_pct
        if prev_monthly_pnl < threshold:
            if not self._cb4_active:
                self._cb4_active = True
                logger.warning(
                    "[CB4] 発動: 前月損益 %.2f%% < 閾値 %.2f%%。"
                    "翌月(%s)ロット50%%削減。",
                    prev_monthly_pnl, threshold, current_month,
                )
        else:
            if self._cb4_active:
                logger.info(
                    "[CB4] 解除: 前月損益 %.2f%% >= 閾値 %.2f%%。",
                    prev_monthly_pnl, threshold,
                )
            self._cb4_active = False
        self._cb4_month = current_month

        # CB2 をリセット（翌月は自動解除）
        if self._cb2_stopped:
            logger.info(
                "[CB2] 月初リセット: %s → %s。", self._cb2_stop_month, current_month
            )
        self._cb2_stopped = False
        self._cb2_stop_month = None

        # 月次損益をリセット
        self._monthly_pnl_pct = 0.0
        if current_balance is not None:
            self._monthly_start_balance = current_balance

        # CB1 の当日停止は月次リセットとは別（翌営業日に自動解除）
        # → record_trade_result / check 内で日付判定で自動解除される

        logger.info(
            "月初リセット完了: %s。CB4_active=%s, CB2_stopped=False",
            current_month, self._cb4_active,
        )

    def release_cb3(self) -> None:
        """
        CB3 を手動解除する（オーナーが問題解決後に呼び出す）。
        """
        logger.warning("[CB3] 手動解除。全戦略の取引を再開します。")
        self._cb3_stopped = False

    # ─────────────────────────────────────────────
    # プライベートヘルパー
    # ─────────────────────────────────────────────

    @staticmethod
    def _make_strategy_key(strategy_id: str, symbol: str, timeframe: str) -> str:
        """戦略を一意に識別するキーを生成する。"""
        return f"{strategy_id}:{symbol}:{timeframe}"

    def _get_strategy_state(self, strategy_key: str) -> Dict[str, Any]:
        """戦略の状態 dict を取得する（なければ初期化して返す）。"""
        if strategy_key not in self._strategy_states:
            self._strategy_states[strategy_key] = {
                "consecutive_losses": 0,
                "cb1_stopped_date": None,
            }
        return self._strategy_states[strategy_key]

    def _is_cb1_active(self, strategy_key: str, today_str: str) -> bool:
        """
        CB1 が当日有効かどうかを返す。

        CB1 は当日のみ有効（翌日には自動解除）。
        """
        state = self._get_strategy_state(strategy_key)
        stopped_date = state.get("cb1_stopped_date")
        if stopped_date is None:
            return False
        if stopped_date != today_str:
            # 翌日以降 → 自動解除
            logger.info(
                "[CB1] %s の当日停止を自動解除（停止日: %s, 今日: %s）",
                strategy_key, stopped_date, today_str,
            )
            state["cb1_stopped_date"] = None
            state["consecutive_losses"] = 0
            self._strategy_states[strategy_key] = state
            return False
        return True

    def _build_cb_status(
        self,
        cb1: bool,
    ) -> Dict[str, Any]:
        """cb_status dict を組み立てる。"""
        return {
            "cb1": cb1,
            "cb2": self._cb2_stopped,
            "cb3": self._cb3_stopped,
            "cb4_lot_modifier": CB4_LOT_MODIFIER if self._cb4_active else 1.0,
        }

    @staticmethod
    def _today_str() -> str:
        """今日の日付文字列 'YYYYMMDD' を返す（UTC）。"""
        return datetime.now(timezone.utc).strftime("%Y%m%d")

    @staticmethod
    def _current_month_str() -> str:
        """現在月の文字列 'YYYYMM' を返す（UTC）。"""
        return datetime.now(timezone.utc).strftime("%Y%m")
