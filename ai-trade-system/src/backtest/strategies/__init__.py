"""
戦略レジストリ — FX戦略モジュール

使い方:
    from src.backtest.strategies import load_strategy, list_strategies

    # 利用可能な戦略IDを確認
    print(list_strategies())
    # ['bb_reversion', 'mtf_confluence', 'rsi_divergence', 'london_breakout', 'ha_trend']

    # 戦略をロードしてシグナル生成
    strategy = load_strategy("bb_reversion")
    result_df = strategy.generate_signals(df, params={}, filters={})

    # 関数形式でも使用可能
    from src.backtest.strategies import generate_signals
    result_df = generate_signals("ha_trend", df, params={}, filters={"use_ema": True})
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Type

import pandas as pd

from .base import BaseStrategy
from .bb_reversion import BBReversionStrategy
from .mtf_confluence import MTFConfluenceStrategy
from .rsi_divergence import RSIDivergenceStrategy
from .london_breakout import LondonBreakoutStrategy
from .ha_trend import HATrendStrategy

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 戦略レジストリ
# ---------------------------------------------------------------------------

_STRATEGY_REGISTRY: Dict[str, Type[BaseStrategy]] = {
    "bb_reversion": BBReversionStrategy,
    "mtf_confluence": MTFConfluenceStrategy,
    "rsi_divergence": RSIDivergenceStrategy,
    "london_breakout": LondonBreakoutStrategy,
    "ha_trend": HATrendStrategy,
}


def list_strategies() -> List[str]:
    """
    利用可能な戦略IDの一覧を返す。

    Returns:
        List[str]: 戦略IDのリスト
    """
    return list(_STRATEGY_REGISTRY.keys())


def load_strategy(strategy_id: str) -> BaseStrategy:
    """
    戦略IDから戦略インスタンスをロードする。

    Args:
        strategy_id: 戦略ID（例: "bb_reversion"）

    Returns:
        BaseStrategy: 戦略インスタンス

    Raises:
        ValueError: 未登録の戦略IDを指定した場合
    """
    if strategy_id not in _STRATEGY_REGISTRY:
        available = list_strategies()
        raise ValueError(
            f"Unknown strategy_id: '{strategy_id}'. Available: {available}"
        )

    strategy_class = _STRATEGY_REGISTRY[strategy_id]
    instance = strategy_class()
    logger.debug("Loaded strategy: %s", strategy_id)
    return instance


def generate_signals(
    strategy_id: str,
    df: pd.DataFrame,
    params: Optional[Dict[str, Any]] = None,
    filters: Optional[Dict[str, bool]] = None,
) -> pd.DataFrame:
    """
    戦略IDを指定してシグナルを生成する簡易API。

    Args:
        strategy_id: 戦略ID
        df: OHLCVデータ
        params: 戦略パラメータ（Noneなら DEFAULT_PARAMS 使用）
        filters: フィルター設定（Noneなら全フィルターOFF）

    Returns:
        pd.DataFrame: シグナルDF（signal / tp_price / sl_price / hold_bars）
    """
    strategy = load_strategy(strategy_id)
    p = params or {}
    f = filters or {}

    logger.info(
        "generate_signals: strategy=%s | filters=%s", strategy_id, f
    )
    return strategy.generate_signals(df, p, f)


def get_default_params(strategy_id: str) -> Dict[str, Any]:
    """
    指定戦略のデフォルトパラメータを返す。

    Args:
        strategy_id: 戦略ID

    Returns:
        Dict[str, Any]: デフォルトパラメータ
    """
    strategy = load_strategy(strategy_id)
    return dict(getattr(strategy, "DEFAULT_PARAMS", {}))


def get_param_grid(strategy_id: str) -> Dict[str, list]:
    """
    指定戦略のパラメータグリッド（工程4最適化用）を返す。

    Args:
        strategy_id: 戦略ID

    Returns:
        Dict[str, list]: パラメータグリッド
    """
    strategy_class = _STRATEGY_REGISTRY.get(strategy_id)
    if strategy_class is None:
        raise ValueError(f"Unknown strategy_id: '{strategy_id}'")

    # 各モジュールから PARAM_GRID を取得
    module_map = {
        "bb_reversion": "bb_reversion",
        "mtf_confluence": "mtf_confluence",
        "rsi_divergence": "rsi_divergence",
        "london_breakout": "london_breakout",
        "ha_trend": "ha_trend",
    }

    import importlib
    module_name = f"src.backtest.strategies.{module_map[strategy_id]}"
    try:
        mod = importlib.import_module(
            f".{module_map[strategy_id]}", package="src.backtest.strategies"
        )
        return dict(getattr(mod, "PARAM_GRID", {}))
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# パッケージレベルの公開シンボル
# ---------------------------------------------------------------------------

__all__ = [
    "list_strategies",
    "load_strategy",
    "generate_signals",
    "get_default_params",
    "get_param_grid",
    "BaseStrategy",
    "BBReversionStrategy",
    "MTFConfluenceStrategy",
    "RSIDivergenceStrategy",
    "LondonBreakoutStrategy",
    "HATrendStrategy",
]
