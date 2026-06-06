"""人気分布ベース WIN5 モデル

画像（JRA-VAN の WIN5 結果一覧）から起こした「各レース当選馬の人気」だけを使い、
人気順位の経験分布から WIN5 の買い目を最適化・評価するための自己完結モジュール。

出走馬の特徴量を必要とせず、結果データのみで完結する。
"""

from .loader import (
    load_results,
    load_target_races,
    winning_popularities,
    rounds_with_pops,
    POP_COLS,
)
from .model import PopularityModel
from .strategy import uniform_strategies, greedy_budget_frontier
from .backtest import backtest_uniform
from .odds import (
    Horse,
    Race,
    Selection,
    EVLine,
    EVPlan,
    implied_win_probs,
    optimize_win5,
    best_within_budget,
    combination_fair_odds,
    enumerate_ev_lines,
    optimize_win5_ev,
)
from .calibration import fit_beta, load_history

__all__ = [
    "load_results",
    "load_target_races",
    "winning_popularities",
    "rounds_with_pops",
    "POP_COLS",
    "PopularityModel",
    "uniform_strategies",
    "greedy_budget_frontier",
    "backtest_uniform",
    "Horse",
    "Race",
    "Selection",
    "EVLine",
    "EVPlan",
    "implied_win_probs",
    "optimize_win5",
    "best_within_budget",
    "combination_fair_odds",
    "enumerate_ev_lines",
    "optimize_win5_ev",
    "fit_beta",
    "load_history",
]
