"""固定比率法による資金管理"""

import logging

from config.settings import FIXED_FRACTION_RATE, MIN_BET_AMOUNT

logger = logging.getLogger(__name__)


def fixed_fraction_bet(
    bankroll: float,
    fraction: float = FIXED_FRACTION_RATE,
    min_bet: float = MIN_BET_AMOUNT,
) -> float:
    """固定比率法でベット額を算出する

    Args:
        bankroll: 現在の資金
        fraction: 資金に対する比率(デフォルト2%)
        min_bet: 最小ベット額

    Returns:
        bet_amount (100円単位)
    """
    if bankroll <= 0:
        return 0.0

    bet = bankroll * fraction

    if bet < min_bet:
        return 0.0

    # 100円単位
    return float(int(bet / 100) * 100)


def progressive_fraction_bet(
    bankroll: float,
    base_fraction: float = FIXED_FRACTION_RATE,
    edge: float = 0.0,
    confidence: float = 0.5,
) -> float:
    """エッジと確信度に基づく可変比率ベット

    Args:
        bankroll: 現在の資金
        base_fraction: 基本比率
        edge: 推定エッジ(モデル確率-暗示確率)
        confidence: モデルの確信度(0-1)

    Returns:
        bet_amount (100円単位)
    """
    if bankroll <= 0 or edge <= 0:
        return 0.0

    # エッジが大きいほど比率を上げる(ただし上限あり)
    adjusted = base_fraction * (1.0 + min(edge * 10, 2.0)) * confidence
    adjusted = min(adjusted, 0.10)  # 最大10%

    bet = bankroll * adjusted
    if bet < MIN_BET_AMOUNT:
        return 0.0

    return float(int(bet / 100) * 100)
