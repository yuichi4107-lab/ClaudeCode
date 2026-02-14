"""オッズ特徴量 (~6個)"""

import numpy as np


def build_odds_features(
    win_odds: float | None,
    num_runners: int,
    popularity: int | None = None,
    field_odds: list[float] | None = None,
) -> dict[str, float]:
    """オッズ関連の特徴量を構築する"""
    f: dict[str, float] = {}

    if win_odds is not None and win_odds > 0:
        f["win_odds"] = win_odds
        f["log_odds"] = float(np.log(win_odds))

        # 暗示確率(控除前)
        implied_prob = 1.0 / win_odds
        f["implied_prob"] = implied_prob
    else:
        f["win_odds"] = 10.0
        f["log_odds"] = float(np.log(10.0))
        f["implied_prob"] = 0.1

    # 人気順
    f["popularity"] = float(popularity) if popularity else float(num_runners / 2)

    # 人気比率
    if num_runners > 0:
        f["popularity_ratio"] = f["popularity"] / float(num_runners)
    else:
        f["popularity_ratio"] = 0.5

    # 本命との倍率比
    if field_odds and len(field_odds) > 0:
        min_odds = min(o for o in field_odds if o and o > 0)
        if min_odds > 0 and win_odds and win_odds > 0:
            f["odds_vs_favorite"] = win_odds / min_odds
        else:
            f["odds_vs_favorite"] = 1.0
    else:
        f["odds_vs_favorite"] = 1.0

    return f
