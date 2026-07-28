"""レース順の実績傾向にもとづく WIN5 買い目提案。

各レース順(1〜5)について「勝ち馬が上位 k 番人気以内に入った実績割合」P_i(rank<=k) を
ヒストリカルに推定し、予算（点数）制約のもとで Π_i P_i(rank<=k_i) を最大化するよう
各レース順の購入頭数 k_i を貪欲配分する。堅い回は絞り、荒れる回は手広くなる。

当日のオッズが無くても「人気順位の上位 k 頭を買う」という形で使える。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List

import numpy as np
import pandas as pd

from .crosstab import POS_COLS


def position_cum_probs(df: pd.DataFrame, max_rank: int = 18) -> Dict[int, np.ndarray]:
    """レース順ごとの累積勝率 P(rank<=k)（index=k, 0..max_rank）を返す。"""
    out: Dict[int, np.ndarray] = {}
    for i, pc in enumerate(POS_COLS, start=1):
        ranks = df[pc].dropna().astype(int)
        counts = np.zeros(max_rank + 1, dtype=float)
        for r in ranks:
            if 1 <= r <= max_rank:
                counts[r] += 1.0
        cum = np.cumsum(counts / counts.sum()) if counts.sum() > 0 else np.zeros(max_rank + 1)
        out[i] = cum
    return out


@dataclass
class PositionPlan:
    k_per_pos: List[int]
    cum_per_pos: List[float]
    points: int
    cost_yen: int
    hit_prob: float
    per_pos: List[dict] = field(default_factory=list)

    @property
    def breakeven_payout_yen(self) -> float:
        return (self.cost_yen / self.hit_prob) if self.hit_prob > 0 else float("inf")


def _snapshot(cums, k, unit_yen, max_rank) -> PositionPlan:
    def cum_at(pos, kk):
        return float(cums[pos][min(kk, max_rank)])

    points = math.prod(k)
    hit = 1.0
    per_pos = []
    cum_list = []
    for i in range(5):
        c = cum_at(i + 1, k[i])
        hit *= c
        cum_list.append(c)
        per_pos.append({"pos": f"{i+1}R目", "k": k[i], "cum_prob": c})
    return PositionPlan(
        k_per_pos=list(k),
        cum_per_pos=cum_list,
        points=points,
        cost_yen=points * unit_yen,
        hit_prob=hit,
        per_pos=per_pos,
    )


def position_frontier(
    df: pd.DataFrame, max_points: int = 20_000, unit_yen: int = 100, max_rank: int = 18
) -> List[PositionPlan]:
    """点数を増やしながら的中確率を最大化する貪欲フロンティア（レース順ごとに頭数配分）。"""
    cums = position_cum_probs(df, max_rank)

    def cum_at(pos, kk):
        return float(cums[pos][min(kk, max_rank)])

    def hit_for(kk: List[int]) -> float:
        h = 1.0
        for j in range(5):
            h *= cum_at(j + 1, kk[j])
        return h

    # 各順位で初めて累積勝率が正になる人気順位（その順を非0にするのに必要な頭数）
    first_pos = {}
    for i in range(5):
        arr = cums[i + 1]
        nz = np.nonzero(arr > 0)[0]
        first_pos[i] = int(nz[0]) if len(nz) else max_rank + 1

    k = [1] * 5
    frontier = [_snapshot(cums, k, unit_yen, max_rank)]
    while math.prod(k) < max_points:
        cur_pts = math.prod(k)
        cur_hit = hit_for(k)
        # hit=0 を招く「累積勝率0」の順位があれば、まず正になるまで増やす
        zeros = [i for i in range(5) if cum_at(i + 1, k[i]) <= 0
                 and first_pos[i] <= max_rank and k[i] < max_rank]
        if cur_hit <= 0 and zeros:
            i = min(zeros, key=lambda i: first_pos[i] - k[i])  # 正にするのが最も安い順位
            k[i] += 1
            if math.prod(k) > max_points:
                break
            frontier.append(_snapshot(cums, k, unit_yen, max_rank))
            continue
        # 通常の貪欲: 的中確率の伸び / 追加点数 が最大の順位を増やす
        best_i, best_score = -1, 0.0
        for i in range(5):
            if k[i] >= max_rank:
                continue
            if cum_at(i + 1, k[i] + 1) <= cum_at(i + 1, k[i]):
                continue  # これ以上増やしても伸びない（実績上 1.0 到達など）
            trial = list(k)
            trial[i] += 1
            d = math.prod(trial) - cur_pts
            if d <= 0:
                continue
            score = (hit_for(trial) - cur_hit) / d
            if score > best_score:
                best_score, best_i = score, i
        if best_i < 0:
            break
        k[best_i] += 1
        if math.prod(k) > max_points:
            break
        frontier.append(_snapshot(cums, k, unit_yen, max_rank))
    return frontier


def position_buy_plan(
    df: pd.DataFrame, budget_yen: int = 10_000, unit_yen: int = 100, max_rank: int = 18
) -> PositionPlan:
    """予算内で的中確率が最大の『レース順ごとの購入頭数』提案を返す。"""
    max_points = max(1, budget_yen // unit_yen)
    frontier = position_frontier(df, max_points=max_points, unit_yen=unit_yen, max_rank=max_rank)
    feasible = [p for p in frontier if p.cost_yen <= budget_yen]
    return max(feasible, key=lambda p: p.hit_prob)
