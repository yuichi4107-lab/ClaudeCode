"""Kelly基準による資金管理

Kelly基準: f* = (bp - q) / b
b = 配当倍率 - 1
p = 的中確率
q = 1 - p

1/4 Kelly推奨(リスク軽減)
"""

import logging

from config.settings import KELLY_FRACTION, MAX_BET_RATIO, MIN_BET_AMOUNT

logger = logging.getLogger(__name__)


def kelly_criterion(
    probability: float,
    odds: float,
    bankroll: float,
    fraction: float = KELLY_FRACTION,
    max_ratio: float = MAX_BET_RATIO,
    min_bet: float = MIN_BET_AMOUNT,
) -> dict[str, float]:
    """Kelly基準でベット額を算出する

    Args:
        probability: 的中確率
        odds: 配当倍率(投資額に対する配当の倍率)
        bankroll: 現在の資金
        fraction: Kellyの適用割合(1/4推奨)
        max_ratio: 最大ベット比率
        min_bet: 最小ベット額

    Returns:
        bet_amount, kelly_fraction, full_kelly, edge 等
    """
    if probability <= 0 or odds <= 0 or bankroll <= 0:
        return {
            "bet_amount": 0.0,
            "kelly_fraction": 0.0,
            "full_kelly": 0.0,
            "edge": 0.0,
            "should_bet": False,
        }

    b = odds - 1.0  # netの倍率
    p = probability
    q = 1.0 - p

    # フルKelly
    if b <= 0:
        full_kelly = 0.0
    else:
        full_kelly = (b * p - q) / b

    # エッジ
    edge = p * odds - 1.0

    # 賭けるべきでない場合
    if full_kelly <= 0 or edge <= 0:
        return {
            "bet_amount": 0.0,
            "kelly_fraction": 0.0,
            "full_kelly": full_kelly,
            "edge": edge,
            "should_bet": False,
        }

    # 分数Kellyを適用
    adjusted_kelly = full_kelly * fraction

    # 最大ベット比率で制限
    adjusted_kelly = min(adjusted_kelly, max_ratio)

    bet_amount = bankroll * adjusted_kelly

    # 最低ベット額
    if bet_amount < min_bet:
        bet_amount = 0.0

    # 100円単位に丸める
    bet_amount = int(bet_amount / 100) * 100

    return {
        "bet_amount": float(bet_amount),
        "kelly_fraction": adjusted_kelly,
        "full_kelly": full_kelly,
        "edge": edge,
        "should_bet": bet_amount > 0,
    }


def multi_race_kelly(
    race_probs: list[float],
    expected_odds: float,
    bankroll: float,
    fraction: float = KELLY_FRACTION,
) -> dict[str, float]:
    """Win5全体のKelly計算

    Args:
        race_probs: 各レースの的中確率のリスト(5レース)
        expected_odds: 期待される配当倍率
        bankroll: 現在の資金
    """
    # Win5全体の的中確率
    total_prob = 1.0
    for p in race_probs:
        total_prob *= p

    return kelly_criterion(
        probability=total_prob,
        odds=expected_odds,
        bankroll=bankroll,
        fraction=fraction,
    )
