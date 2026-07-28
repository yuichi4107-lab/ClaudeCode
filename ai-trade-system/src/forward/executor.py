"""
注文執行モジュール — FX Phase1 フォワードテスト用

シグナルを受け取り、サーキットブレーカーチェック後に Saxo Sim へ注文を発注する。

トレードログ:
    logs/forward/trades_YYYYMMDD.jsonl
    1 行 1 トレード（JSONL形式）

使い方:
    from src.forward.executor import ForwardExecutor
    from src.forward.circuit_breaker import CircuitBreaker
    from src.backtest.portfolio_config_loader import (
        load_portfolio_config, get_circuit_breaker_config
    )

    portfolio = load_portfolio_config(portfolio_id="pattern_C_growth")
    cb_config = get_circuit_breaker_config(portfolio)
    cb = CircuitBreaker(cb_config)

    executor = ForwardExecutor(
        saxo_client=saxo,
        portfolio_config=portfolio,
        circuit_breaker=cb,
        dry_run=True,
    )

    result = executor.execute_signal(signal)
    # result = {"status": "executed"|"skipped"|"cb_blocked", "order_id": ..., ...}
"""

import json
import logging
import math
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# ─── ロットサイズ計算定数 ───
SAXO_UNITS_PER_LOT: int = 100_000   # 1ロット = 10万通貨
SAXO_MIN_LOT: float = 0.01          # 最小ロット（= 1000通貨）
SAXO_MIN_UNITS: int = 1_000         # 最小注文単位（units）

# デフォルトのログディレクトリ（PROJECT_ROOT/logs/forward）
_THIS_DIR = os.path.dirname(__file__)
_PROJECT_ROOT = os.path.abspath(os.path.join(_THIS_DIR, "../.."))
DEFAULT_LOG_DIR = os.path.join(_PROJECT_ROOT, "logs", "forward")


class ForwardExecutor:
    """
    シグナルに基づいて Saxo Sim へ注文を発注する。

    機能:
        - BUY/SELL シグナルで成行注文
        - パターン C の配分比率に基づくロットサイズ計算
        - サーキットブレーカーによる注文制御
        - 注文結果の JSONL ログ記録

    Args:
        saxo_client:      SaxoClient インスタンス（None の場合は API 未接続）
        portfolio_config: load_portfolio_config() の返り値
        circuit_breaker:  CircuitBreaker インスタンス
        dry_run:          True なら実際の注文は出さずログのみ記録
        log_dir:          トレードログ出力ディレクトリ（None でデフォルト）
    """

    def __init__(
        self,
        saxo_client: Optional[Any],
        portfolio_config: Dict[str, Any],
        circuit_breaker: Optional[Any] = None,
        dry_run: bool = True,
        log_dir: Optional[str] = None,
    ):
        self.saxo = saxo_client
        self.portfolio = portfolio_config
        self.cb = circuit_breaker
        self.dry_run = dry_run
        self.log_dir = log_dir or DEFAULT_LOG_DIR

        # ログディレクトリを自動作成
        os.makedirs(self.log_dir, exist_ok=True)

        # ポートフォリオ設定から共通値を抽出
        self.total_capital: float = float(
            portfolio_config.get("total_capital", 100_000)
        )
        self.global_lot_multiplier: float = float(
            portfolio_config.get("lot_multiplier", 1.0)
        )

        # strategy_key -> entry のマップを事前構築
        # key: "{strategy_id}:{symbol}:{timeframe}"
        self._strategy_map: Dict[str, Dict[str, Any]] = {}
        for entry in portfolio_config.get("strategies", []):
            key = self._make_strategy_key(
                entry.get("strategy_id", ""),
                entry.get("symbol", ""),
                entry.get("timeframe", ""),
            )
            self._strategy_map[key] = entry

        logger.info(
            "ForwardExecutor 初期化: capital=%.0f, lot_multiplier=%.2f, "
            "dry_run=%s, strategies=%d件",
            self.total_capital,
            self.global_lot_multiplier,
            self.dry_run,
            len(self._strategy_map),
        )

    # ─────────────────────────────────────────────
    # パブリックメソッド
    # ─────────────────────────────────────────────

    def execute_signal(self, signal: Dict[str, Any]) -> Dict[str, Any]:
        """
        シグナルを評価し、CB チェック通過後に注文を発注する。

        シグナル dict が持つべきキー:
            strategy:  戦略ID（例: "mtf_confluence"）
            symbol:    通貨ペア（例: "USDJPY"）
            timeframe: 時間足（例: "1h"）
            signal:    "BUY" | "SELL" | "FLAT"
            price:     エントリー価格（float）
            sl:        ストップロス価格（float）
            tp:        テイクプロフィット価格（float）

        Args:
            signal: シグナル dict

        Returns:
            {
                "status": "executed" | "skipped" | "cb_blocked",
                "order_id": str | None,
                "strategy": str,
                "symbol": str,
                "timeframe": str,
                "side": str,
                "amount": int,         # 発注 units
                "lot_size": float,     # ロット数
                "price": float,
                "sl": float,
                "tp": float,
                "cb_status": dict,
                "reason": str,
            }
        """
        strategy_id = signal.get("strategy", "")
        symbol = signal.get("symbol", "")
        timeframe = signal.get("timeframe", "")
        side_raw = signal.get("signal", "FLAT")

        # FLAT シグナルはスキップ
        if side_raw not in ("BUY", "SELL"):
            result = self._build_result(
                status="skipped",
                reason=f"シグナルが FLAT: {side_raw}",
                signal=signal,
                order_id=None,
                amount=0,
                lot_size=0.0,
                cb_status={"cb1": False, "cb2": False, "cb3": False, "cb4_lot_modifier": 1.0},
            )
            self._write_trade_log(result)
            return result

        price = self._safe_float(signal.get("price"))
        sl = self._safe_float(signal.get("sl"))
        tp = self._safe_float(signal.get("tp"))

        # 価格未設定チェック
        if price is None or price <= 0:
            result = self._build_result(
                status="skipped",
                reason=f"price が未設定または不正: {signal.get('price')}",
                signal=signal,
                order_id=None,
                amount=0,
                lot_size=0.0,
                cb_status={"cb1": False, "cb2": False, "cb3": False, "cb4_lot_modifier": 1.0},
            )
            self._write_trade_log(result)
            return result

        # ─── CB チェック ───
        cb_status = {"cb1": False, "cb2": False, "cb3": False, "cb4_lot_modifier": 1.0}
        lot_modifier = 1.0

        if self.cb is not None:
            cb_result = self.cb.check(strategy_id, signal)
            cb_status = cb_result.get("cb_status", cb_status)
            lot_modifier = cb_result.get("lot_modifier", 1.0)

            if not cb_result.get("allowed", True):
                result = self._build_result(
                    status="cb_blocked",
                    reason=cb_result.get("reason", "CB blocked"),
                    signal=signal,
                    order_id=None,
                    amount=0,
                    lot_size=0.0,
                    cb_status=cb_status,
                )
                logger.info(
                    "CB ブロック: %s %s %s - %s",
                    strategy_id, symbol, timeframe, cb_result.get("reason"),
                )
                self._write_trade_log(result)
                return result

        # ─── ロットサイズ計算 ───
        strategy_key = self._make_strategy_key(strategy_id, symbol, timeframe)
        strategy_entry = self._strategy_map.get(strategy_key, {})
        lot_size = self._calculate_lot_size(
            strategy_entry=strategy_entry,
            price=price,
            sl=sl,
            lot_modifier=lot_modifier,
        )
        units = self._lot_to_units(lot_size)

        if units < SAXO_MIN_UNITS:
            result = self._build_result(
                status="skipped",
                reason=f"ロットサイズが最小単位未満: lot={lot_size:.4f}, units={units}",
                signal=signal,
                order_id=None,
                amount=units,
                lot_size=lot_size,
                cb_status=cb_status,
            )
            logger.warning("ロット不足でスキップ: %s %s units=%d", strategy_id, symbol, units)
            self._write_trade_log(result)
            return result

        # ─── 注文発注 ───
        if self.dry_run:
            order_id = f"dry_{int(datetime.now(timezone.utc).timestamp())}"
            logger.info(
                "[DRY RUN] %s %s %s %s units=%d price=%.5f sl=%.5f tp=%.5f",
                strategy_id, symbol, timeframe, side_raw, units, price,
                sl if sl else 0.0, tp if tp else 0.0,
            )
            result = self._build_result(
                status="executed",
                reason="dry_run",
                signal=signal,
                order_id=order_id,
                amount=units,
                lot_size=lot_size,
                cb_status=cb_status,
                price=price,
                sl=sl,
                tp=tp,
            )
            self._write_trade_log(result)
            return result

        # ─── 実注文（dry_run=False） ───
        try:
            if side_raw == "BUY":
                order_resp = self.saxo.market_buy(symbol, float(units))
            else:
                order_resp = self.saxo.market_sell(symbol, float(units))

            order_id = str(order_resp.get("id", order_resp.get("OrderId", "")))

            logger.info(
                "注文発注成功: %s %s %s %s units=%d order_id=%s",
                strategy_id, symbol, timeframe, side_raw, units, order_id,
            )

            result = self._build_result(
                status="executed",
                reason="ok",
                signal=signal,
                order_id=order_id,
                amount=units,
                lot_size=lot_size,
                cb_status=cb_status,
                price=price,
                sl=sl,
                tp=tp,
            )
            self._write_trade_log(result)
            return result

        except Exception as exc:
            logger.error(
                "注文発注失敗（例外をキャッチしてスキップ）: %s %s %s: %s",
                strategy_id, symbol, side_raw, exc,
                exc_info=True,
            )
            result = self._build_result(
                status="skipped",
                reason=f"注文発注エラー: {exc}",
                signal=signal,
                order_id=None,
                amount=units,
                lot_size=lot_size,
                cb_status=cb_status,
                price=price,
                sl=sl,
                tp=tp,
            )
            self._write_trade_log(result)
            return result

    # ─────────────────────────────────────────────
    # プライベートメソッド
    # ─────────────────────────────────────────────

    def _calculate_lot_size(
        self,
        strategy_entry: Dict[str, Any],
        price: float,
        sl: Optional[float],
        lot_modifier: float,
    ) -> float:
        """
        パターン C の設定に基づくロットサイズを計算する。

        計算式:
            capital × (allocation_pct / 100) × risk_per_trade_pct / 100
            / sl_pct × lot_multiplier × lot_modifier / (UNITS_PER_LOT)

        SL幅 (sl_pct) は:
            1. strategy_entry["params"]["sl_pct"] を優先
            2. price と sl から計算（(price - sl) / price の絶対値）
            3. デフォルト 0.005（0.5%）

        Args:
            strategy_entry: portfolio_config の strategies エントリ
            price:          エントリー価格
            sl:             ストップロス価格（None の場合は sl_pct を使用）
            lot_modifier:   CB4 発動時の削減係数（1.0 = 通常）

        Returns:
            float: Saxo 最小単位(0.01)に切り捨てたロット数
        """
        allocation_pct = float(strategy_entry.get("capital_allocation_pct", 20)) / 100.0
        risk_pct = float(strategy_entry.get("risk_per_trade_pct", 2.0)) / 100.0
        lot_multiplier = float(
            strategy_entry.get("lot_multiplier", self.global_lot_multiplier)
        )

        # SL幅の決定
        params = strategy_entry.get("params", {})
        sl_pct = float(params.get("sl_pct", 0.005))

        # sl 価格が有効な場合は実際の幅を計算（上書き）
        if sl is not None and sl > 0 and price > 0:
            computed_sl_pct = abs(price - sl) / price
            if 0 < computed_sl_pct < 1.0:
                sl_pct = computed_sl_pct

        # SL幅がゼロなら最小値を設定
        if sl_pct <= 0:
            sl_pct = 0.001

        # ロット計算
        # capital × allocation_pct × risk_pct / sl_pct = ポジション価値（円）
        # lot = position_value / UNITS_PER_LOT（USDJPY の場合, 1通貨≒1円として近似）
        capital_allocated = self.total_capital * allocation_pct
        risk_amount = capital_allocated * risk_pct
        position_value = risk_amount / sl_pct

        raw_lots = (position_value / SAXO_UNITS_PER_LOT) * lot_multiplier * lot_modifier

        # 切り捨て（Saxo 最小単位 0.01）
        lot = math.floor(raw_lots / SAXO_MIN_LOT) * SAXO_MIN_LOT
        lot = round(lot, 2)

        logger.debug(
            "lot計算: alloc=%.0f%%, risk=%.1f%%, sl_pct=%.4f, "
            "position_value=%.0f, raw_lots=%.4f, final_lot=%.2f",
            allocation_pct * 100, risk_pct * 100, sl_pct,
            position_value, raw_lots, lot,
        )

        return max(lot, 0.0)

    @staticmethod
    def _lot_to_units(lot: float) -> int:
        """ロット数を Saxo 注文 units に変換する（1ロット = 100,000 units）。"""
        return int(lot * SAXO_UNITS_PER_LOT)

    @staticmethod
    def _make_strategy_key(strategy_id: str, symbol: str, timeframe: str) -> str:
        """戦略を一意に識別するキーを生成する。"""
        return f"{strategy_id}:{symbol}:{timeframe}"

    @staticmethod
    def _safe_float(value: Any) -> Optional[float]:
        """float に変換する。None または nan は None を返す。"""
        if value is None:
            return None
        try:
            f = float(value)
            if math.isnan(f) or math.isinf(f):
                return None
            return f
        except (TypeError, ValueError):
            return None

    def _build_result(
        self,
        status: str,
        reason: str,
        signal: Dict[str, Any],
        order_id: Optional[str],
        amount: int,
        lot_size: float,
        cb_status: Dict[str, Any],
        price: Optional[float] = None,
        sl: Optional[float] = None,
        tp: Optional[float] = None,
    ) -> Dict[str, Any]:
        """execute_signal の返り値 dict を組み立てる。"""
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return {
            "timestamp": ts,
            "status": status,
            "reason": reason,
            "strategy": signal.get("strategy", ""),
            "symbol": signal.get("symbol", ""),
            "timeframe": signal.get("timeframe", ""),
            "side": signal.get("signal", ""),
            "amount": amount,
            "lot_size": lot_size,
            "price": price if price is not None else signal.get("price"),
            "sl": sl if sl is not None else signal.get("sl"),
            "tp": tp if tp is not None else signal.get("tp"),
            "order_id": order_id,
            "dry_run": self.dry_run,
            "cb_status": cb_status,
        }

    def _write_trade_log(self, record: Dict[str, Any]) -> None:
        """
        トレードログを JSONL ファイルに追記する。

        ファイル名: logs/forward/trades_YYYYMMDD.jsonl
        """
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        log_path = os.path.join(self.log_dir, f"trades_{today}.jsonl")

        # nan / inf を JSON セーフな値に変換
        def sanitize(v: Any) -> Any:
            if isinstance(v, float):
                if math.isnan(v):
                    return None
                if math.isinf(v):
                    return None
            return v

        sanitized = {k: sanitize(v) for k, v in record.items()}

        try:
            line = json.dumps(sanitized, ensure_ascii=False)
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
            logger.debug("トレードログ記録: %s", line[:200])
        except Exception as exc:
            logger.error("トレードログ書き込みエラー: %s", exc)
