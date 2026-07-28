"""
FX専用ルールベースバックテストエンジン

概要:
    工程3の戦略モジュール（src/backtest/strategies/）を呼び出し、
    OHLCVデータに対してシグナル生成→損益計算→結果保存を実行する。

    既存の runner.py（Gemini Vision方式）とは別実装であり、既存コードへの変更なし。

使い方:
    from src.backtest.fx_runner import FXRunner

    runner = FXRunner(
        strategy_id="bb_reversion",
        symbol="USDJPY",
        timeframe="1h",
        data_path="data/fx/ohlcv/USDJPY_1h.csv",
    )
    result = runner.run(params={}, filters={"use_sma200": True})
    runner.save_result(result, "results/fx_phase1/")

CLI実行:
    python -m src.backtest.fx_runner --strategy bb_reversion --symbol USDJPY --timeframe 1h

設計方針:
    - 1トレード = シグナル発火 → hold_bars バー後に強制クローズ（TP/SLより先に到達した方）
    - 複数ポジション同時保有なし（シグナルが出ても前ポジションがある間はスキップ）
    - fee_rate はスプレッド相当のコスト（デフォルト USDJPY=0.00002、EURJPY=0.00003）
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

# プロジェクトルートをsys.pathに追加
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.backtest.strategies import load_strategy, list_strategies

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# デフォルト設定
# ---------------------------------------------------------------------------

FEE_RATE_BY_SYMBOL: Dict[str, float] = {
    "USDJPY": 0.00002,  # 0.2pip相当（要件定義M3対応）
    "EURJPY": 0.00003,  # 0.3pip相当
}

DEFAULT_FEE_RATE = 0.00002


# ---------------------------------------------------------------------------
# バックテストエンジン
# ---------------------------------------------------------------------------


class FXRunner:
    """
    FX戦略のルールベースバックテストランナー。

    Attributes:
        strategy_id: 使用する戦略のID
        symbol: 通貨ペア（例: "USDJPY"）
        timeframe: 時間足（例: "1h"）
        data_path: OHLCVデータのCSVパス
        fee_rate: スプレッド相当コスト（片道）
    """

    def __init__(
        self,
        strategy_id: str,
        symbol: str,
        timeframe: str,
        data_path: str,
        fee_rate: Optional[float] = None,
    ) -> None:
        """
        FXRunnerを初期化する。

        Args:
            strategy_id: 戦略ID（list_strategies()で確認）
            symbol: 通貨ペア
            timeframe: 時間足
            data_path: OHLCVデータのCSVパス
            fee_rate: スプレッドコスト。Noneならsymbolから自動設定
        """
        self.strategy_id = strategy_id
        self.symbol = symbol.upper()
        self.timeframe = timeframe
        self.data_path = data_path
        self.fee_rate = fee_rate or FEE_RATE_BY_SYMBOL.get(self.symbol, DEFAULT_FEE_RATE)

        self.strategy = load_strategy(strategy_id)
        logger.info(
            "FXRunner initialized: strategy=%s, symbol=%s, tf=%s, fee=%.5f",
            strategy_id, symbol, timeframe, self.fee_rate
        )

    def load_data(self) -> pd.DataFrame:
        """
        CSVからOHLCVデータを読み込む。

        Returns:
            pd.DataFrame: OHLCVデータ

        Raises:
            FileNotFoundError: データファイルが存在しない場合
        """
        if not os.path.exists(self.data_path):
            raise FileNotFoundError(f"Data file not found: {self.data_path}")

        df = pd.read_csv(self.data_path)
        logger.info("Loaded data: %s (%d rows)", self.data_path, len(df))

        # datetimeカラムの型変換
        if "datetime" in df.columns:
            df["datetime"] = pd.to_datetime(df["datetime"])

        return df

    def run(
        self,
        params: Optional[Dict[str, Any]] = None,
        filters: Optional[Dict[str, bool]] = None,
        df: Optional[pd.DataFrame] = None,
    ) -> Dict[str, Any]:
        """
        バックテストを実行する。

        Args:
            params: 戦略パラメータ（Noneなら DEFAULT_PARAMS）
            filters: フィルター設定（Noneなら全フィルターOFF）
            df: OHLCVデータ（Noneなら data_path から読み込む）

        Returns:
            Dict: バックテスト結果（result.json フォーマット準拠）
        """
        p = params or {}
        f = filters or {}

        if df is None:
            df = self.load_data()

        start_time = datetime.now()
        logger.info(
            "FXRunner.run: strategy=%s, symbol=%s, tf=%s, rows=%d",
            self.strategy_id, self.symbol, self.timeframe, len(df)
        )

        # シグナル生成
        signals_df = self.strategy.generate_signals(df, p, f)

        # バックテスト実行
        trades = self._simulate_trades(df, signals_df)

        # 統計計算
        stats = self._calc_stats(trades, df)

        elapsed = (datetime.now() - start_time).total_seconds()
        logger.info(
            "FXRunner.run: completed in %.1fs | trades=%d | win_rate=%.1f%%",
            elapsed, stats["total_trades"], stats["win_rate_pct"]
        )

        result = {
            "strategy_id": self.strategy_id,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "params": p,
            "filters": f,
            "stats": stats,
            "equity_curve": self._calc_equity_curve(trades),
            "trades": trades,
            "run_timestamp": datetime.now().isoformat(),
        }

        return result

    def _simulate_trades(
        self,
        df: pd.DataFrame,
        signals_df: pd.DataFrame,
    ) -> List[Dict[str, Any]]:
        """
        シグナルからトレードをシミュレートする。

        ルール:
            - ポジション保有中は新規シグナルをスキップ
            - エントリー価格 = シグナルバーの終値
            - TP/SL到達でクローズ
            - hold_bars バー経過で強制クローズ

        Args:
            df: OHLCVデータ
            signals_df: シグナルDF（signal / tp_price / sl_price / hold_bars）

        Returns:
            List[Dict]: トレードリスト
        """
        trades = []
        in_position = False
        entry_pos = 0
        entry_price = 0.0
        entry_signal = 0
        tp_price = 0.0
        sl_price = 0.0
        hold_bars_max = 0

        close_arr = df["close"].values
        high_arr = df["high"].values
        low_arr = df["low"].values
        signals = signals_df["signal"].values
        tp_arr = signals_df["tp_price"].values
        sl_arr = signals_df["sl_price"].values
        hb_arr = signals_df["hold_bars"].values
        n = len(df)

        for pos in range(n):
            if in_position:
                bars_held = pos - entry_pos

                # TP/SL到達チェック
                if entry_signal == 1:  # ロング
                    hit_tp = high_arr[pos] >= tp_price
                    hit_sl = low_arr[pos] <= sl_price
                else:  # ショート
                    hit_tp = low_arr[pos] <= tp_price
                    hit_sl = high_arr[pos] >= sl_price

                exit_price = None
                exit_reason = None

                if hit_tp:
                    exit_price = tp_price
                    exit_reason = "tp"
                elif hit_sl:
                    exit_price = sl_price
                    exit_reason = "sl"
                elif bars_held >= hold_bars_max:
                    exit_price = close_arr[pos]
                    exit_reason = "timeout"

                if exit_price is not None:
                    # 損益計算
                    if entry_signal == 1:
                        pnl_pct = (exit_price - entry_price) / entry_price - self.fee_rate * 2
                    else:
                        pnl_pct = (entry_price - exit_price) / entry_price - self.fee_rate * 2

                    trades.append({
                        "entry_pos": entry_pos,
                        "exit_pos": pos,
                        "direction": "long" if entry_signal == 1 else "short",
                        "entry_price": entry_price,
                        "exit_price": exit_price,
                        "exit_reason": exit_reason,
                        "hold_bars": bars_held,
                        "pnl_pct": pnl_pct,
                        "is_win": pnl_pct > 0,
                    })

                    in_position = False
                    continue

            else:
                # 新規エントリー
                sig = signals[pos]
                if sig != 0 and not np.isnan(tp_arr[pos]) and not np.isnan(sl_arr[pos]):
                    in_position = True
                    entry_pos = pos
                    entry_price = close_arr[pos]
                    entry_signal = int(sig)
                    tp_price = tp_arr[pos]
                    sl_price = sl_arr[pos]
                    hold_bars_max = max(1, int(hb_arr[pos]))

        return trades

    def _calc_stats(
        self,
        trades: List[Dict[str, Any]],
        df: pd.DataFrame,
    ) -> Dict[str, Any]:
        """
        トレードリストから統計指標を計算する。

        Args:
            trades: トレードリスト
            df: OHLCVデータ（期間計算用）

        Returns:
            Dict: 統計指標
        """
        if not trades:
            return {
                "total_trades": 0,
                "win_rate_pct": 0.0,
                "profit_factor": 0.0,
                "monthly_return_pct": 0.0,
                "max_drawdown_pct": 0.0,
                "sharpe_ratio": 0.0,
                "sortino_ratio": 0.0,
                "calmar_ratio": 0.0,
                "avg_holding_bars": 0.0,
            }

        pnl_arr = np.array([t["pnl_pct"] for t in trades])
        wins = pnl_arr[pnl_arr > 0]
        losses = pnl_arr[pnl_arr <= 0]

        total_trades = len(trades)
        win_count = len(wins)
        win_rate = win_count / total_trades * 100 if total_trades > 0 else 0.0

        gross_profit = wins.sum() if len(wins) > 0 else 0.0
        gross_loss = abs(losses.sum()) if len(losses) > 0 else 0.0
        pf = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        # 月次リターン（バックテスト期間で割る）
        total_return = float(pnl_arr.sum())
        n_months = self._calc_months(df)
        monthly_return = total_return / n_months * 100 if n_months > 0 else 0.0

        # エクイティカーブからMDD計算
        equity = np.cumprod(1 + pnl_arr)
        rolling_max = np.maximum.accumulate(equity)
        drawdown = (equity - rolling_max) / rolling_max
        max_dd = float(abs(drawdown.min())) * 100 if len(drawdown) > 0 else 0.0

        # シャープ・ソルティノ・カルマー比
        pnl_std = float(pnl_arr.std()) if len(pnl_arr) > 1 else 0.0
        downside = pnl_arr[pnl_arr < 0]
        downside_std = float(downside.std()) if len(downside) > 1 else 0.0

        sharpe = float(pnl_arr.mean() / pnl_std) if pnl_std > 0 else 0.0
        sortino = float(pnl_arr.mean() / downside_std) if downside_std > 0 else 0.0
        calmar = float(monthly_return / max_dd) if max_dd > 0 else 0.0

        avg_hold = float(np.mean([t["hold_bars"] for t in trades]))

        return {
            "total_trades": total_trades,
            "win_rate_pct": round(win_rate, 2),
            "profit_factor": round(pf, 3),
            "monthly_return_pct": round(monthly_return, 3),
            "max_drawdown_pct": round(max_dd, 3),
            "sharpe_ratio": round(sharpe, 3),
            "sortino_ratio": round(sortino, 3),
            "calmar_ratio": round(calmar, 3),
            "avg_holding_bars": round(avg_hold, 1),
        }

    def _calc_equity_curve(self, trades: List[Dict[str, Any]]) -> List[float]:
        """
        累積エクイティカーブを計算する（1.0スタート）。

        Args:
            trades: トレードリスト

        Returns:
            List[float]: エクイティカーブ
        """
        if not trades:
            return [1.0]

        equity = 1.0
        curve = [equity]
        for t in trades:
            equity *= 1 + t["pnl_pct"]
            curve.append(round(equity, 6))

        return curve

    def _calc_months(self, df: pd.DataFrame) -> float:
        """
        OHLCVデータの期間（月数）を計算する。

        Args:
            df: OHLCVデータ

        Returns:
            float: 月数
        """
        if "datetime" in df.columns:
            dt = pd.to_datetime(df["datetime"])
        elif "timestamp" in df.columns:
            ts = df["timestamp"]
            unit = "ms" if ts.max() > 1e12 else "s"
            dt = pd.to_datetime(ts, unit=unit)
        else:
            return 18.0  # デフォルト18ヶ月

        if len(dt) < 2:
            return 1.0

        delta_days = (dt.iloc[-1] - dt.iloc[0]).days
        return max(1.0, delta_days / 30.44)

    def save_result(
        self,
        result: Dict[str, Any],
        output_dir: str,
        trades: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """
        バックテスト結果をJSONファイルに保存する。

        Args:
            result: バックテスト結果dict
            output_dir: 保存ディレクトリ（自動作成）
            trades: トレード詳細（省略可）

        Returns:
            str: 保存先ディレクトリのパス
        """
        dir_name = f"{self.strategy_id}_{self.symbol}_{self.timeframe}"
        save_path = os.path.join(output_dir, dir_name)
        os.makedirs(save_path, exist_ok=True)

        result_path = os.path.join(save_path, "result.json")
        with open(result_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        logger.info("Result saved: %s", result_path)

        if trades:
            trades_path = os.path.join(save_path, "trades.csv")
            pd.DataFrame(trades).to_csv(trades_path, index=False)
            logger.info("Trades saved: %s", trades_path)

        return save_path


# ---------------------------------------------------------------------------
# CLI エントリーポイント
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI実行のエントリーポイント。"""
    import argparse

    parser = argparse.ArgumentParser(description="FX戦略バックテスト実行")
    parser.add_argument("--strategy", required=True, choices=list_strategies())
    parser.add_argument("--symbol", default="USDJPY")
    parser.add_argument("--timeframe", default="1h")
    parser.add_argument("--data-dir", default="data/fx/ohlcv")
    parser.add_argument("--output-dir", default="results/fx_phase1")
    parser.add_argument("--use-sma200", action="store_true")
    parser.add_argument("--use-atr", action="store_true")
    parser.add_argument("--use-session", action="store_true")
    parser.add_argument("--use-event", action="store_true")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO))

    symbol_key = args.symbol.replace("/", "").upper()
    data_path = os.path.join(
        PROJECT_ROOT, args.data_dir, f"{symbol_key}_{args.timeframe}.csv"
    )

    runner = FXRunner(
        strategy_id=args.strategy,
        symbol=symbol_key,
        timeframe=args.timeframe,
        data_path=data_path,
    )

    filters = {
        "use_sma200": args.use_sma200,
        "use_atr": args.use_atr,
        "use_session": args.use_session,
        "use_event": args.use_event,
    }

    result = runner.run(params={}, filters=filters)

    print(f"\n=== Backtest Result: {args.strategy} {symbol_key} {args.timeframe} ===")
    stats = result["stats"]
    print(f"  Total Trades  : {stats['total_trades']}")
    print(f"  Win Rate      : {stats['win_rate_pct']:.1f}%")
    print(f"  Profit Factor : {stats['profit_factor']:.3f}")
    print(f"  Monthly Return: {stats['monthly_return_pct']:.3f}%")
    print(f"  Max Drawdown  : {stats['max_drawdown_pct']:.3f}%")
    print(f"  Sharpe Ratio  : {stats['sharpe_ratio']:.3f}")

    output_dir = os.path.join(PROJECT_ROOT, args.output_dir)
    save_path = runner.save_result(result, output_dir)
    print(f"\nResult saved to: {save_path}")


if __name__ == "__main__":
    main()
