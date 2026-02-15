"""バックテスト評価 - Sharpe ratio, ROI, Max Drawdown"""

import logging

import numpy as np
import pandas as pd

from fx_trader.config import settings
from fx_trader.features.builder import FeatureBuilder
from fx_trader.model.registry import load_model
from fx_trader.storage.repository import Repository

logger = logging.getLogger(__name__)


class BacktestEvaluator:
    """モデルのバックテスト評価"""

    def __init__(self, model_name: str, repo: Repository = None):
        self.model_name = model_name
        self.repo = repo or Repository()
        self.builder = FeatureBuilder(self.repo)
        self.model, self.metadata = load_model(model_name)

    def run_backtest(
        self,
        instrument: str,
        granularity: str = "H1",
        from_date: str = None,
        to_date: str = None,
        threshold: float = 0.55,
        stop_loss_pips: float = None,
        take_profit_pips: float = None,
        spread_pips: float = None,
        forward_periods: int = 5,
    ) -> dict:
        """バックテストを実行

        Args:
            instrument: 通貨ペア
            granularity: 足の種類
            from_date: 開始日
            to_date: 終了日
            threshold: シグナル閾値
            stop_loss_pips: 損切り幅
            take_profit_pips: 利確幅
            spread_pips: スプレッド
            forward_periods: ポジション保持期間（足数）

        Returns:
            バックテスト結果dict
        """
        sl_pips = stop_loss_pips or settings.DEFAULT_STOP_LOSS_PIPS
        tp_pips = take_profit_pips or settings.DEFAULT_TAKE_PROFIT_PIPS
        spread = spread_pips or settings.BACKTEST_SPREAD_PIPS

        pip_loc = settings.INSTRUMENTS.get(instrument, {}).get("pip_location", -2)
        pip_value = 10 ** pip_loc  # 1 pip の価格単位

        # データ取得
        df = self.repo.get_candles(instrument, granularity, from_date, to_date)
        if df.empty or len(df) < 300:
            logger.warning("Not enough data for backtest: %d rows", len(df))
            return {}

        # 特徴量生成
        features = self.builder._compute_features(df)
        model_features = self.metadata.get("features", [])
        if model_features:
            for col in model_features:
                if col not in features.columns:
                    features[col] = np.nan
            features = features[model_features]

        valid_mask = features.notna().all(axis=1)
        features = features[valid_mask]
        df = df[valid_mask]

        # 予測
        probs = self.model.predict_proba(features)[:, 1]

        # シミュレーション
        trades = []
        balance = settings.BACKTEST_INITIAL_BALANCE
        equity_curve = []

        i = 0
        while i < len(df) - forward_periods:
            prob_up = probs[i]

            if prob_up >= threshold:
                side = "buy"
            elif prob_up <= (1 - threshold):
                side = "sell"
            else:
                equity_curve.append({"timestamp": df.index[i], "equity": balance})
                i += 1
                continue

            entry_price = df["close"].iloc[i]

            # forward_periods 先までの価格推移を確認
            pnl_pips = 0.0
            exit_reason = "timeout"

            for j in range(1, forward_periods + 1):
                if i + j >= len(df):
                    break

                if side == "buy":
                    # 高値でTP判定、安値でSL判定
                    high_pips = (df["high"].iloc[i + j] - entry_price) / pip_value - spread
                    low_pips = (df["low"].iloc[i + j] - entry_price) / pip_value - spread

                    if low_pips <= -sl_pips:
                        pnl_pips = -sl_pips
                        exit_reason = "stop_loss"
                        break
                    if high_pips >= tp_pips:
                        pnl_pips = tp_pips
                        exit_reason = "take_profit"
                        break
                else:
                    high_pips = (entry_price - df["low"].iloc[i + j]) / pip_value - spread
                    low_pips = (entry_price - df["high"].iloc[i + j]) / pip_value - spread

                    if low_pips <= -sl_pips:
                        pnl_pips = -sl_pips
                        exit_reason = "stop_loss"
                        break
                    if high_pips >= tp_pips:
                        pnl_pips = tp_pips
                        exit_reason = "take_profit"
                        break

            # タイムアウトの場合は期間末の終値で決済
            if exit_reason == "timeout":
                end_idx = min(i + forward_periods, len(df) - 1)
                if side == "buy":
                    pnl_pips = (df["close"].iloc[end_idx] - entry_price) / pip_value - spread
                else:
                    pnl_pips = (entry_price - df["close"].iloc[end_idx]) / pip_value - spread

            pnl_amount = pnl_pips * pip_value * settings.DEFAULT_TRADE_UNITS
            balance += pnl_amount

            trades.append({
                "timestamp": str(df.index[i]),
                "side": side,
                "entry_price": entry_price,
                "pnl_pips": round(pnl_pips, 2),
                "pnl_amount": round(pnl_amount, 2),
                "exit_reason": exit_reason,
                "confidence": float(prob_up),
            })

            equity_curve.append({"timestamp": df.index[i], "equity": balance})
            i += forward_periods  # ポジション保持期間分スキップ

        if not trades:
            logger.warning("No trades generated in backtest")
            return {"total_trades": 0}

        trades_df = pd.DataFrame(trades)
        equity_df = pd.DataFrame(equity_curve)

        # --- 評価メトリクス ---
        total_trades = len(trades_df)
        wins = (trades_df["pnl_pips"] > 0).sum()
        losses = (trades_df["pnl_pips"] < 0).sum()
        win_rate = wins / total_trades if total_trades > 0 else 0

        total_pnl = trades_df["pnl_amount"].sum()
        avg_pnl_pips = trades_df["pnl_pips"].mean()
        max_win = trades_df["pnl_pips"].max()
        max_loss = trades_df["pnl_pips"].min()

        # Profit Factor
        gross_profit = trades_df[trades_df["pnl_pips"] > 0]["pnl_amount"].sum()
        gross_loss = abs(trades_df[trades_df["pnl_pips"] < 0]["pnl_amount"].sum())
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        # Sharpe Ratio (年換算)
        returns = trades_df["pnl_amount"] / settings.BACKTEST_INITIAL_BALANCE
        sharpe = (returns.mean() / returns.std() * np.sqrt(252)) if returns.std() > 0 else 0

        # Max Drawdown
        if not equity_df.empty:
            peak = equity_df["equity"].cummax()
            drawdown = (equity_df["equity"] - peak) / peak
            max_drawdown = drawdown.min()
        else:
            max_drawdown = 0

        # ROI
        roi = (balance - settings.BACKTEST_INITIAL_BALANCE) / settings.BACKTEST_INITIAL_BALANCE

        result = {
            "instrument": instrument,
            "granularity": granularity,
            "model_name": self.model_name,
            "total_trades": total_trades,
            "wins": int(wins),
            "losses": int(losses),
            "win_rate": round(win_rate, 4),
            "total_pnl": round(total_pnl, 2),
            "avg_pnl_pips": round(avg_pnl_pips, 2),
            "max_win_pips": round(max_win, 2),
            "max_loss_pips": round(max_loss, 2),
            "profit_factor": round(profit_factor, 4),
            "sharpe_ratio": round(sharpe, 4),
            "max_drawdown": round(max_drawdown, 4),
            "roi": round(roi, 4),
            "final_balance": round(balance, 2),
        }

        logger.info(
            "Backtest: %d trades, WR=%.1f%%, PF=%.2f, Sharpe=%.2f, DD=%.1f%%, ROI=%.1f%%",
            total_trades, win_rate * 100, profit_factor, sharpe, max_drawdown * 100, roi * 100,
        )

        return result
