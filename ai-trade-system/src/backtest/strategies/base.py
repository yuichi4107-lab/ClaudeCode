"""
基底クラスとユーティリティ関数 — FX戦略共通モジュール

全戦略が継承する抽象基底クラス `BaseStrategy` と、
シグナル生成・TP/SL計算に使う共通ユーティリティを提供する。

設計方針:
- generate_signals() は全戦略共通のシグネチャを持つ
- signal: 1=ロングエントリー, -1=ショートエントリー, 0=何もしない
- tp_price / sl_price: 絶対価格（pip差ではなく価格レベル）
- hold_bars: 最大保有期間（バー数）
- データ不足・欠損・異常値はログを出して 0 シグナルで返す（例外は投げない）

参考:
- QuantifiedStrategies.com: ルールベースFX戦略のベストプラクティス
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# シグナル定数
SIGNAL_LONG = 1
SIGNAL_SHORT = -1
SIGNAL_NONE = 0

# 必須カラム
REQUIRED_COLUMNS = {"open", "high", "low", "close"}


# ---------------------------------------------------------------------------
# ユーティリティ関数
# ---------------------------------------------------------------------------


def validate_dataframe(df: pd.DataFrame, min_rows: int = 50) -> bool:
    """
    DataFrameの基本品質チェックを行う。

    Args:
        df: 検証対象のOHLCV DataFrame
        min_rows: 必要最低行数

    Returns:
        bool: 有効なら True
    """
    if df is None or df.empty:
        logger.warning("DataFrame is None or empty")
        return False

    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        logger.warning("Missing columns: %s", missing)
        return False

    if len(df) < min_rows:
        logger.warning(
            "Insufficient rows: %d (required: %d)", len(df), min_rows
        )
        return False

    # OHLC整合性チェック
    invalid_mask = (
        (df["high"] < df["open"])
        | (df["high"] < df["close"])
        | (df["high"] < df["low"])
        | (df["low"] > df["open"])
        | (df["low"] > df["close"])
    )
    invalid_count = int(invalid_mask.sum())
    if invalid_count > 0:
        logger.warning("OHLC inconsistency found in %d rows", invalid_count)

    return True


def make_signal_df(df: pd.DataFrame) -> pd.DataFrame:
    """
    シグナルカラム群をゼロ初期化して返す。

    Args:
        df: 元DataFrame（インデックスのみ使用）

    Returns:
        pd.DataFrame: signal / tp_price / sl_price / hold_bars カラムを持つ DataFrame
    """
    result = df.copy()
    result["signal"] = SIGNAL_NONE
    result["tp_price"] = np.nan
    result["sl_price"] = np.nan
    result["hold_bars"] = 0
    return result


def calc_tp_sl(
    entry_price: float,
    direction: int,
    tp_pct: float,
    sl_pct: float,
) -> tuple[float, float]:
    """
    TP/SL価格をエントリー価格とパーセントから計算する。

    Args:
        entry_price: エントリー価格
        direction: 1=ロング, -1=ショート
        tp_pct: 利確幅（例: 0.003 = 0.3%）
        sl_pct: 損切り幅（例: 0.005 = 0.5%）

    Returns:
        (tp_price, sl_price)
    """
    if direction == SIGNAL_LONG:
        tp_price = entry_price * (1.0 + tp_pct)
        sl_price = entry_price * (1.0 - sl_pct)
    else:
        tp_price = entry_price * (1.0 - tp_pct)
        sl_price = entry_price * (1.0 + sl_pct)
    return tp_price, sl_price


def empty_signals(df: pd.DataFrame, reason: str = "") -> pd.DataFrame:
    """
    エラー時またはデータ不足時にゼロシグナルのDataFrameを返す。

    Args:
        df: 元DataFrame
        reason: ログに記録する理由

    Returns:
        pd.DataFrame: 全シグナル=0のDataFrame
    """
    if reason:
        logger.info("Returning empty signals: %s", reason)
    return make_signal_df(df)


# ---------------------------------------------------------------------------
# 抽象基底クラス
# ---------------------------------------------------------------------------


class BaseStrategy(ABC):
    """
    全FX戦略の抽象基底クラス。

    サブクラスは generate_signals() を実装する。
    __init__ では戦略名とデフォルトパラメータを設定する。
    """

    strategy_id: str = "base"
    description: str = "Base strategy"

    def __call__(
        self,
        df: pd.DataFrame,
        params: Dict[str, Any],
        filters: Dict[str, bool],
    ) -> pd.DataFrame:
        """generate_signals() への省略呼び出しを可能にする。"""
        return self.generate_signals(df, params, filters)

    @abstractmethod
    def generate_signals(
        self,
        df: pd.DataFrame,
        params: Dict[str, Any],
        filters: Dict[str, bool],
    ) -> pd.DataFrame:
        """
        シグナルを生成する。

        Args:
            df: OHLCVデータ（timestamp/datetime, open, high, low, close, volume）
            params: 戦略固有パラメータ（DEFAULT_PARAMSをベースに上書き）
            filters: フィルター有効/無効フラグ

        Returns:
            pd.DataFrame: 元DFに以下カラムを追加して返す
                - signal    : 1=ロングエントリー, -1=ショートエントリー, 0=何もしない
                - tp_price  : 利確価格（絶対値）
                - sl_price  : 損切り価格（絶対値）
                - hold_bars : 最大保有期間（バー数）
        """

    def get_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        DEFAULT_PARAMSにユーザー指定paramsを上書きして返す。

        Args:
            params: 上書きするパラメータ

        Returns:
            Dict: マージ済みパラメータ
        """
        merged = dict(getattr(self, "DEFAULT_PARAMS", {}))
        merged.update(params)
        return merged
