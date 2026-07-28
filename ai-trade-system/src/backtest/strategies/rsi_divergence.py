"""
戦略3: RSI Divergence + MACD Confirm

ロジック:
    ブリッシュダイバージェンス（ロング）:
        - 価格: 直近N本内に安値更新（低安値）
        - RSI(14): 同期間に安値切り上げ（高RSI安値）
        - MACDヒストグラム: 負→正に転換でエントリー確認

    ベアリッシュダイバージェンス（ショート）:
        - 価格: 直近N本内に高値更新（高高値）
        - RSI(14): 同期間に高値切り下げ（低RSI高値）
        - MACDヒストグラム: 正→負に転換でエントリー確認

エグジット:
    - TP: RR=1.5 相当
    - SL: 直近スイング安値/高値の外側
    - 最大保有: hold_bars バー

ピーク検出:
    scipy.signal.argrelmin/argrelmax を使用。
    scipy未インストール時は簡易実装（pandas rolling）にフォールバック。

期待勝率の根拠:
    - QuantifiedStrategies: RSI + MACD組合せで73%勝率（235トレード）
    - ForexBee: RSIダイバージェンス単体で86%勝率（サンプル少、参考値）
    - USDJPY: 中銀介入後の調整でRSIダイバージェンスが形成されやすい

参考文献:
    - https://www.quantifiedstrategies.com/macd-and-rsi-strategy/
    - https://forexbee.co/rsi-divergence-indicator-guide/
    - https://fibalgo.com/education/rsi-divergence-trading-strategy-fear-market
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd

try:
    import pandas_ta as ta
except ImportError:
    ta = None  # type: ignore

try:
    from scipy.signal import argrelmin, argrelmax

    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False

from .base import (
    BaseStrategy,
    SIGNAL_LONG,
    SIGNAL_SHORT,
    SIGNAL_NONE,
    validate_dataframe,
    make_signal_df,
    calc_tp_sl,
    empty_signals,
)
from .filters import (
    sma200_long_filter,
    sma200_short_filter,
    atr_volatility_filter,
    session_time_filter,
    economic_event_filter,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# パラメータ定義
# ---------------------------------------------------------------------------

DEFAULT_PARAMS: Dict[str, Any] = {
    "rsi_period": 14,
    "rsi_oversold": 30.0,           # ロングはRSI安値がこの水準以下
    "rsi_overbought": 70.0,         # ショートはRSI高値がこの水準以上
    "macd_fast": 12,
    "macd_slow": 26,
    "macd_signal": 9,
    "div_lookback": 30,             # ダイバージェンス検出の遡り期間（バー数）
    "swing_order": 3,               # ピーク検出の近傍サイズ
    "tp_pct": 0.004,                # 0.4%
    "sl_pct": 0.003,                # 0.3%（RR=1.5に相当）
    "hold_bars": 20,
}

PARAM_GRID: Dict[str, list] = {
    "rsi_period": [10, 14],
    "rsi_oversold": [25.0, 30.0, 35.0],
    "div_lookback": [20, 30, 40],
    "swing_order": [2, 3, 5],
    "tp_pct": [0.003, 0.004, 0.006],
    "sl_pct": [0.002, 0.003, 0.005],
    "hold_bars": [10, 20, 30],
}

MIN_ROWS = 60

# リアルタイムシグナル生成に必要な最低バー数
# RSI period(14) + div_lookback(最大40) + swing_order(最大5) → 40本
MIN_BARS = 40


# ---------------------------------------------------------------------------
# ピーク検出ユーティリティ
# ---------------------------------------------------------------------------


def _find_local_minima(series: pd.Series, order: int) -> np.ndarray:
    """
    ローカル最小値のインデックス配列を返す。

    Args:
        series: 検索対象のSeries
        order: 近傍サイズ（この範囲内で最小値を探す）

    Returns:
        np.ndarray: ローカル最小値の整数インデックス
    """
    values = series.values
    if SCIPY_AVAILABLE:
        indices = argrelmin(values, order=order)[0]
    else:
        # 簡易実装: rolling min と一致する位置
        roll_min = series.rolling(window=2 * order + 1, center=True).min()
        mask = series == roll_min
        indices = np.where(mask.values)[0]
    return indices


def _find_local_maxima(series: pd.Series, order: int) -> np.ndarray:
    """
    ローカル最大値のインデックス配列を返す。

    Args:
        series: 検索対象のSeries
        order: 近傍サイズ

    Returns:
        np.ndarray: ローカル最大値の整数インデックス
    """
    values = series.values
    if SCIPY_AVAILABLE:
        indices = argrelmax(values, order=order)[0]
    else:
        roll_max = series.rolling(window=2 * order + 1, center=True).max()
        mask = series == roll_max
        indices = np.where(mask.values)[0]
    return indices


# ---------------------------------------------------------------------------
# ダイバージェンス検出
# ---------------------------------------------------------------------------


def _detect_bullish_divergence(
    close: pd.Series,
    rsi: pd.Series,
    current_idx: int,
    lookback: int,
    order: int,
    rsi_oversold: float,
) -> bool:
    """
    current_idx 時点でのブリッシュダイバージェンスを検出する。

    条件:
        - current_idx から lookback 本前の範囲内に少なくとも2つのRSI安値がある
        - 価格安値: 後の安値 < 前の安値（安値更新）
        - RSI安値: 後のRSI安値 > 前のRSI安値（安値切り上げ）
        - 最新のRSI安値が rsi_oversold 以下

    Args:
        close: closeのSeries
        rsi: RSIのSeries
        current_idx: 現在の整数インデックス位置
        lookback: 遡り期間
        order: ピーク検出の近傍サイズ
        rsi_oversold: RSI過売り閾値

    Returns:
        bool: ブリッシュダイバージェンス検出なら True
    """
    start_idx = max(0, current_idx - lookback)
    close_window = close.iloc[start_idx : current_idx + 1]
    rsi_window = rsi.iloc[start_idx : current_idx + 1]

    # RSIの局所最小値を取得
    rsi_troughs = _find_local_minima(rsi_window, order)

    if len(rsi_troughs) < 2:
        return False

    # 最新2つのRSI安値を比較
    t1, t2 = rsi_troughs[-2], rsi_troughs[-1]
    price_t1 = float(close_window.iloc[t1])
    price_t2 = float(close_window.iloc[t2])
    rsi_t1 = float(rsi_window.iloc[t1])
    rsi_t2 = float(rsi_window.iloc[t2])

    # ブリッシュダイバージェンス: 価格は安値更新、RSIは切り上げ
    price_diverge = price_t2 < price_t1
    rsi_diverge = rsi_t2 > rsi_t1
    rsi_in_oversold = rsi_t2 <= rsi_oversold

    return price_diverge and rsi_diverge and rsi_in_oversold


def _detect_bearish_divergence(
    close: pd.Series,
    rsi: pd.Series,
    current_idx: int,
    lookback: int,
    order: int,
    rsi_overbought: float,
) -> bool:
    """
    current_idx 時点でのベアリッシュダイバージェンスを検出する。

    Args:
        close: closeのSeries
        rsi: RSIのSeries
        current_idx: 現在の整数インデックス位置
        lookback: 遡り期間
        order: ピーク検出の近傍サイズ
        rsi_overbought: RSI過買い閾値

    Returns:
        bool: ベアリッシュダイバージェンス検出なら True
    """
    start_idx = max(0, current_idx - lookback)
    close_window = close.iloc[start_idx : current_idx + 1]
    rsi_window = rsi.iloc[start_idx : current_idx + 1]

    rsi_peaks = _find_local_maxima(rsi_window, order)

    if len(rsi_peaks) < 2:
        return False

    p1, p2 = rsi_peaks[-2], rsi_peaks[-1]
    price_p1 = float(close_window.iloc[p1])
    price_p2 = float(close_window.iloc[p2])
    rsi_p1 = float(rsi_window.iloc[p1])
    rsi_p2 = float(rsi_window.iloc[p2])

    price_diverge = price_p2 > price_p1
    rsi_diverge = rsi_p2 < rsi_p1
    rsi_in_overbought = rsi_p2 >= rsi_overbought

    return price_diverge and rsi_diverge and rsi_in_overbought


# ---------------------------------------------------------------------------
# メイン関数
# ---------------------------------------------------------------------------


def generate_signals(
    df: pd.DataFrame,
    params: Dict[str, Any],
    filters: Dict[str, bool],
) -> pd.DataFrame:
    """
    RSIダイバージェンス + MACDクロス確認のシグナルを生成する。

    Args:
        df: OHLCVデータ
        params: 戦略パラメータ（DEFAULT_PARAMSをベースに上書き）
        filters: フィルター有効/無効フラグ
            - use_sma200 (bool): SMA200トレンドフィルター
            - use_atr    (bool): ATRボラティリティフィルター
            - use_session (bool): セッション時間フィルター
            - use_event  (bool): 重要指標回避フィルター

    Returns:
        pd.DataFrame: 元DFに signal / tp_price / sl_price / hold_bars カラムを追加
    """
    p = {**DEFAULT_PARAMS, **params}

    if not validate_dataframe(df, min_rows=MIN_ROWS):
        return empty_signals(df, "RSI Divergence: data validation failed")

    logger.info(
        "RSI Divergence: generating signals | rows=%d | div_lookback=%d",
        len(df),
        p["div_lookback"],
    )

    result = make_signal_df(df)

    try:
        close = df["close"].reset_index(drop=True)
        high = df["high"].reset_index(drop=True)
        low = df["low"].reset_index(drop=True)

        # RSI計算
        if ta is not None:
            rsi = ta.rsi(close, length=p["rsi_period"])
        else:
            delta = close.diff()
            gain = delta.clip(lower=0).rolling(p["rsi_period"]).mean()
            loss = (-delta.clip(upper=0)).rolling(p["rsi_period"]).mean()
            rs = gain / loss.replace(0, np.nan)
            rsi = 100 - (100 / (1 + rs))

        # MACD計算
        if ta is not None:
            macd_df = ta.macd(
                close,
                fast=p["macd_fast"],
                slow=p["macd_slow"],
                signal=p["macd_signal"],
            )
            if macd_df is None or macd_df.empty:
                return empty_signals(df, "RSI Divergence: MACD calculation failed")
            # pandas_ta の列名: MACDh_{fast}_{slow}_{signal}
            hist_col = [c for c in macd_df.columns if "MACDh" in c]
            macd_hist = macd_df[hist_col[0]] if hist_col else macd_df.iloc[:, 2]
        else:
            ema_fast = close.ewm(span=p["macd_fast"], adjust=False).mean()
            ema_slow = close.ewm(span=p["macd_slow"], adjust=False).mean()
            macd_line = ema_fast - ema_slow
            signal_line = macd_line.ewm(span=p["macd_signal"], adjust=False).mean()
            macd_hist = macd_line - signal_line

        # フィルター用マスクを事前計算
        sma200_long_ok = sma200_long_filter(df) if filters.get("use_sma200", False) else pd.Series(True, index=df.index)
        sma200_short_ok = sma200_short_filter(df) if filters.get("use_sma200", False) else pd.Series(True, index=df.index)
        atr_ok = atr_volatility_filter(df, min_atr=0.10) if filters.get("use_atr", False) else pd.Series(True, index=df.index)
        session_ok = session_time_filter(df, allow_tokyo=False) if filters.get("use_session", False) else pd.Series(True, index=df.index)
        event_ok = economic_event_filter(df) if filters.get("use_event", False) else pd.Series(True, index=df.index)

        # 元のインデックスを整数インデックスにマッピング
        orig_index = df.index.tolist()

        lookback = p["div_lookback"]
        order = p["swing_order"]
        rsi_values = rsi.fillna(50).values
        close_values = close.values
        hist_values = macd_hist.fillna(0).values

        # ループ外で事前に1度だけSeries化（コード品質改善）
        rsi_series = pd.Series(rsi_values)
        close_series = pd.Series(close_values)

        # ダイバージェンスは遡り期間が確保できる位置から走査
        start_scan = max(lookback + order, p["macd_slow"] + p["macd_signal"])

        for pos in range(start_scan, len(df)):
            orig_i = orig_index[pos]

            # セッション・イベントフィルター（両方向で共通）
            if not session_ok.loc[orig_i] or not event_ok.loc[orig_i]:
                continue

            # MACDヒストグラムのゼロクロス（前バーが負、現バーが正）
            macd_bullish_cross = (hist_values[pos - 1] < 0) and (hist_values[pos] >= 0)
            macd_bearish_cross = (hist_values[pos - 1] > 0) and (hist_values[pos] <= 0)

            # ブリッシュダイバージェンス + MACD強気クロス → ロング
            if macd_bullish_cross and sma200_long_ok.loc[orig_i] and atr_ok.loc[orig_i]:
                if _detect_bullish_divergence(
                    close_series, rsi_series, pos, lookback, order, p["rsi_oversold"]
                ):
                    entry = float(close_values[pos])
                    tp, sl = calc_tp_sl(entry, SIGNAL_LONG, p["tp_pct"], p["sl_pct"])
                    result.at[orig_i, "signal"] = SIGNAL_LONG
                    result.at[orig_i, "tp_price"] = tp
                    result.at[orig_i, "sl_price"] = sl
                    result.at[orig_i, "hold_bars"] = p["hold_bars"]
                    logger.debug(
                        "RSI Divergence: LONG signal at pos=%d, entry=%.4f", pos, entry
                    )

            # ベアリッシュダイバージェンス + MACD弱気クロス → ショート
            elif macd_bearish_cross and sma200_short_ok.loc[orig_i] and atr_ok.loc[orig_i]:
                if _detect_bearish_divergence(
                    close_series, rsi_series, pos, lookback, order, p["rsi_overbought"]
                ):
                    entry = float(close_values[pos])
                    tp, sl = calc_tp_sl(entry, SIGNAL_SHORT, p["tp_pct"], p["sl_pct"])
                    result.at[orig_i, "signal"] = SIGNAL_SHORT
                    result.at[orig_i, "tp_price"] = tp
                    result.at[orig_i, "sl_price"] = sl
                    result.at[orig_i, "hold_bars"] = p["hold_bars"]
                    logger.debug(
                        "RSI Divergence: SHORT signal at pos=%d, entry=%.4f", pos, entry
                    )

    except Exception as exc:
        logger.error("RSI Divergence: unexpected error: %s", exc, exc_info=True)
        return empty_signals(df, f"RSI Divergence: error: {exc}")

    long_count = int((result["signal"] == SIGNAL_LONG).sum())
    short_count = int((result["signal"] == SIGNAL_SHORT).sum())
    logger.info(
        "RSI Divergence: signals generated | long=%d | short=%d | total=%d",
        long_count,
        short_count,
        long_count + short_count,
    )

    return result


# ---------------------------------------------------------------------------
# 戦略クラス
# ---------------------------------------------------------------------------


class RSIDivergenceStrategy(BaseStrategy):
    """RSIダイバージェンス + MACDクロス確認戦略。"""

    strategy_id = "rsi_divergence"
    description = "RSI Bullish/Bearish Divergence + MACD Histogram Cross Confirm"
    DEFAULT_PARAMS = DEFAULT_PARAMS

    # リアルタイムシグナル生成に必要な最低バー数
    MIN_BARS: int = MIN_BARS

    def generate_signals(
        self,
        df: pd.DataFrame,
        params: Dict[str, Any],
        filters: Dict[str, bool],
    ) -> pd.DataFrame:
        return generate_signals(df, self.get_params(params), filters)

    def get_latest_signal(
        self,
        ohlcv: pd.DataFrame,
        params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        最新のOHLCVデータから直近のシグナルを1件返す。

        warm-up期間（MIN_BARS本）を含む最新N本のOHLCVを受け取り、
        最後のバーに対応するシグナルを返す。
        データ不足時は例外を投げず FLAT を返す。

        Args:
            ohlcv: 最新N本のOHLCVデータ（MIN_BARS本以上推奨）。
                   カラム: open, high, low, close（volume任意）
            params: 戦略パラメータ（portfolio_config.jsonのparams）

        Returns:
            dict: {
                "signal": "BUY" | "SELL" | "FLAT",
                "price": float,   # 現在の終値
                "sl": float,      # ストップロス価格
                "tp": float,      # テイクプロフィット価格
                "strategy": str,  # 戦略ID
                "symbol": str,    # 通貨ペア（paramsに"symbol"キーがある場合）
                "timeframe": str, # 時間足（paramsに"timeframe"キーがある場合）
                "timestamp": str  # ISOフォーマットのタイムスタンプ（最終バー）
            }
        """
        _flat_base: Dict[str, Any] = {
            "signal": "FLAT",
            "price": float("nan"),
            "sl": float("nan"),
            "tp": float("nan"),
            "strategy": self.strategy_id,
            "symbol": params.get("symbol", ""),
            "timeframe": params.get("timeframe", ""),
            "timestamp": "",
        }

        # warm-up期間チェック
        if ohlcv is None or len(ohlcv) < self.MIN_BARS:
            logger.warning(
                "RSI Divergence get_latest_signal: insufficient bars %d (need %d)",
                0 if ohlcv is None else len(ohlcv),
                self.MIN_BARS,
            )
            return _flat_base

        try:
            merged_params = self.get_params(params)
            filters: Dict[str, bool] = {}
            signals_df = generate_signals(ohlcv, merged_params, filters)

            # 最終行のシグナルを取得
            last_row = signals_df.iloc[-1]
            last_bar = ohlcv.iloc[-1]
            sig_val = int(last_row["signal"])

            if sig_val == SIGNAL_LONG:
                signal_str = "BUY"
            elif sig_val == SIGNAL_SHORT:
                signal_str = "SELL"
            else:
                signal_str = "FLAT"

            # タイムスタンプ取得（インデックスまたはカラムから）
            ts_str = ""
            last_index = signals_df.index[-1]
            if isinstance(last_index, pd.Timestamp):
                ts_str = last_index.isoformat()
            elif "datetime" in ohlcv.columns:
                ts_str = str(ohlcv["datetime"].iloc[-1])
            elif "timestamp" in ohlcv.columns:
                ts_str = str(ohlcv["timestamp"].iloc[-1])

            return {
                "signal": signal_str,
                "price": float(last_bar["close"]),
                "sl": float(last_row["sl_price"]) if not pd.isna(last_row["sl_price"]) else float("nan"),
                "tp": float(last_row["tp_price"]) if not pd.isna(last_row["tp_price"]) else float("nan"),
                "strategy": self.strategy_id,
                "symbol": params.get("symbol", ""),
                "timeframe": params.get("timeframe", ""),
                "timestamp": ts_str,
            }

        except Exception as exc:
            logger.error(
                "RSI Divergence get_latest_signal: unexpected error: %s", exc, exc_info=True
            )
            return _flat_base
