"""特徴量生成 - テクニカル指標をMLモデルの入力に変換"""

import numpy as np
import pandas as pd

from fx_trader.config import settings
from fx_trader.storage.repository import Repository


class FeatureBuilder:
    """OHLCV データからテクニカル指標ベースの特徴量を生成"""

    def __init__(self, repo: Repository = None):
        self.repo = repo or Repository()

    def build_training_set(
        self,
        instrument: str,
        granularity: str = "H1",
        from_date: str = None,
        to_date: str = None,
        forward_periods: int = 5,
    ) -> tuple[pd.DataFrame, pd.Series]:
        """学習用データセットを構築

        Args:
            instrument: 通貨ペア
            granularity: 足の種類
            from_date: 開始日
            to_date: 終了日
            forward_periods: 予測先の足数 (ラベル生成用)

        Returns:
            (X, y): 特徴量DataFrame, ラベルSeries (1=上昇, 0=下降)
        """
        df = self.repo.get_candles(instrument, granularity, from_date, to_date)
        if df.empty:
            return pd.DataFrame(), pd.Series(dtype=int)

        features = self._compute_features(df)

        # ラベル: forward_periods 先の終値が現在より高ければ 1 (買い)
        future_return = df["close"].shift(-forward_periods) / df["close"] - 1
        labels = (future_return > 0).astype(int)

        # NaN を含む行を除去
        valid = features.notna().all(axis=1) & labels.notna()
        return features[valid], labels[valid]

    def build_prediction_features(
        self,
        instrument: str,
        granularity: str = "H1",
        lookback: int = 250,
    ) -> pd.DataFrame:
        """推論用の特徴量を生成（最新データから）

        Args:
            instrument: 通貨ペア
            granularity: 足の種類
            lookback: 必要な過去データ本数

        Returns:
            最新1行の特徴量DataFrame
        """
        df = self.repo.get_candles(instrument, granularity, limit=lookback)
        if df.empty:
            return pd.DataFrame()

        features = self._compute_features(df)
        # 最新行のみ返す
        latest = features.iloc[[-1]].dropna(axis=1, how="all")
        return latest

    def _compute_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """全テクニカル指標を計算"""
        features = pd.DataFrame(index=df.index)

        # --- 移動平均 ---
        for period in settings.FEATURE_LOOKBACK_PERIODS:
            sma = df["close"].rolling(window=period).mean()
            features[f"sma_{period}"] = sma
            features[f"sma_{period}_ratio"] = df["close"] / sma  # 現在価格/SMAの比率

            ema = df["close"].ewm(span=period, adjust=False).mean()
            features[f"ema_{period}"] = ema
            features[f"ema_{period}_ratio"] = df["close"] / ema

        # SMAクロス (短期/長期の比率)
        features["sma_cross_5_20"] = features["sma_5"] / features["sma_20"]
        features["sma_cross_10_50"] = features["sma_10"] / features["sma_50"]
        features["sma_cross_20_100"] = features["sma_20"] / features["sma_100"]

        # --- RSI ---
        features["rsi"] = self._calc_rsi(df["close"], settings.RSI_PERIOD)
        features["rsi_sma"] = features["rsi"].rolling(window=10).mean()

        # --- MACD ---
        ema_fast = df["close"].ewm(span=settings.MACD_FAST, adjust=False).mean()
        ema_slow = df["close"].ewm(span=settings.MACD_SLOW, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=settings.MACD_SIGNAL, adjust=False).mean()
        features["macd"] = macd_line
        features["macd_signal"] = signal_line
        features["macd_hist"] = macd_line - signal_line
        features["macd_hist_diff"] = features["macd_hist"].diff()

        # --- ボリンジャーバンド ---
        bb_sma = df["close"].rolling(window=settings.BOLLINGER_PERIOD).mean()
        bb_std = df["close"].rolling(window=settings.BOLLINGER_PERIOD).std()
        features["bb_upper"] = bb_sma + settings.BOLLINGER_STD * bb_std
        features["bb_lower"] = bb_sma - settings.BOLLINGER_STD * bb_std
        features["bb_width"] = (features["bb_upper"] - features["bb_lower"]) / bb_sma
        features["bb_position"] = (df["close"] - features["bb_lower"]) / (features["bb_upper"] - features["bb_lower"])

        # --- ATR (Average True Range) ---
        features["atr"] = self._calc_atr(df, settings.ATR_PERIOD)
        features["atr_ratio"] = features["atr"] / df["close"]

        # --- ボラティリティ ---
        for period in [5, 10, 20]:
            features[f"volatility_{period}"] = df["close"].pct_change().rolling(window=period).std()

        # --- モメンタム / ROC ---
        for period in [1, 3, 5, 10, 20]:
            features[f"return_{period}"] = df["close"].pct_change(periods=period)

        # --- 出来高 ---
        if "volume" in df.columns and df["volume"].sum() > 0:
            for period in [5, 10, 20]:
                features[f"volume_sma_{period}"] = df["volume"].rolling(window=period).mean()
            features["volume_ratio"] = df["volume"] / df["volume"].rolling(window=20).mean()

        # --- ローソク足パターン ---
        features["body_ratio"] = (df["close"] - df["open"]) / (df["high"] - df["low"]).replace(0, np.nan)
        features["upper_shadow"] = (df["high"] - df[["open", "close"]].max(axis=1)) / (df["high"] - df["low"]).replace(0, np.nan)
        features["lower_shadow"] = (df[["open", "close"]].min(axis=1) - df["low"]) / (df["high"] - df["low"]).replace(0, np.nan)

        # --- 時間特徴量 ---
        if hasattr(df.index, "hour"):
            features["hour"] = df.index.hour
            features["day_of_week"] = df.index.dayofweek
            # 市場セッション (0=アジア, 1=ロンドン, 2=NY)
            features["session"] = pd.cut(
                df.index.hour,
                bins=[-1, 8, 16, 24],
                labels=[0, 1, 2],
            ).astype(float)

        # 生の価格レベル列は除去（SMA等の比率のみ残す）
        drop_cols = [c for c in features.columns if c.startswith(("sma_", "ema_")) and "_ratio" not in c and "cross" not in c]
        features.drop(columns=drop_cols, inplace=True, errors="ignore")
        # ボリンジャーバンドの絶対値も除去
        features.drop(columns=["bb_upper", "bb_lower"], inplace=True, errors="ignore")

        return features

    @staticmethod
    def _calc_rsi(series: pd.Series, period: int = 14) -> pd.Series:
        """RSI (Relative Strength Index) を計算"""
        delta = series.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)

        avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
        avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()

        rs = avg_gain / avg_loss.replace(0, np.nan)
        return 100 - (100 / (1 + rs))

    @staticmethod
    def _calc_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
        """ATR (Average True Range) を計算"""
        high_low = df["high"] - df["low"]
        high_close = (df["high"] - df["close"].shift()).abs()
        low_close = (df["low"] - df["close"].shift()).abs()
        true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        return true_range.rolling(window=period).mean()
