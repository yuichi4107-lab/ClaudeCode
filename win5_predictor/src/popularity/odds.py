"""単勝オッズ＋人気順だけで組み立てる WIN5 モデル。

対象 5 レースの全出走馬の単勝オッズを入力とし、
- オッズ → 暗黙勝率（控除率を除いた市場確率）
- 各レースで「どの馬を買うか」を点数（予算）制約下で的中確率最大に選ぶ
を行う。学習データ不要で当日のオッズだけで完結する。

人気順（人気）はオッズの並び順と一致するかの検証に使う。オッズが無いレースは
2026 実績から推定した P(勝利|k番人気)（PopularityModel）をフォールバックに使える。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Sequence

import numpy as np


@dataclass
class Horse:
    umaban: int
    odds: float
    name: str = ""
    pop: Optional[int] = None  # 人気順（任意・検証用）
    prob: float = 0.0  # 計算後に埋まる暗黙勝率


def implied_win_probs(odds: Sequence[float], beta: float = 1.0) -> np.ndarray:
    """単勝オッズ列から控除率を除いた暗黙勝率を返す。

    q_i = (1/odds_i) / Σ(1/odds_j)。beta!=1 なら人気-穴バイアス補正
    p_i ∝ q_i^beta（beta>1 で本命に寄せる）を掛けて再正規化する。
    """
    o = np.asarray(odds, dtype=float)
    if np.any(o <= 1.0):
        raise ValueError("単勝オッズは 1.0 より大きい必要があります。")
    inv = 1.0 / o
    q = inv / inv.sum()
    if beta != 1.0:
        q = np.power(q, beta)
        q = q / q.sum()
    return q


class Race:
    """1 レースぶんの出走馬とオッズ。勝率降順に並べて保持する。"""

    def __init__(self, horses: List[Horse], beta: float = 1.0, name: str = ""):
        if not horses:
            raise ValueError("出走馬が空です。")
        probs = implied_win_probs([h.odds for h in horses], beta=beta)
        for h, p in zip(horses, probs):
            h.prob = float(p)
        # 勝率降順（=オッズ昇順=人気順）
        self.horses: List[Horse] = sorted(horses, key=lambda h: -h.prob)
        self.name = name
        # 暗黙の人気順を付与し、入力人気との不整合を検出
        self.pop_mismatch: List[int] = []
        for i, h in enumerate(self.horses, start=1):
            if h.pop is not None and h.pop != i:
                self.pop_mismatch.append(h.umaban)

    @property
    def probs(self) -> List[float]:
        return [h.prob for h in self.horses]

    def top(self, k: int) -> List[Horse]:
        return self.horses[:k]

    def cum_prob(self, k: int) -> float:
        return float(sum(h.prob for h in self.horses[:k]))


@dataclass
class Selection:
    points: int
    cost_yen: int
    hit_prob: float
    per_race: List[dict] = field(default_factory=list)  # {race, k, umaban, cum_prob}

    @property
    def breakeven_payout_yen(self) -> float:
        return (self.cost_yen / self.hit_prob) if self.hit_prob > 0 else float("inf")


def _snapshot(races: List[Race], k: List[int], unit_yen: int) -> Selection:
    points = math.prod(k)
    hit = 1.0
    per_race = []
    for r, ki in zip(races, k):
        cp = r.cum_prob(ki)
        hit *= cp
        per_race.append(
            {
                "race": r.name,
                "k": ki,
                "umaban": [h.umaban for h in r.top(ki)],
                "cum_prob": cp,
            }
        )
    return Selection(points=points, cost_yen=points * unit_yen, hit_prob=hit, per_race=per_race)


def optimize_win5(
    races: List[Race], max_points: int = 10_000, unit_yen: int = 100
) -> List[Selection]:
    """点数制約下で WIN5 的中確率を最大化する貪欲フロンティア。

    各レース 1 頭（最上位）から開始し、「1 頭追加したときの的中確率の伸び / 追加点数」が
    最大のレースに馬を足していく。到達した各 (点数, 的中確率) を返す。
    """
    if len(races) != 5:
        raise ValueError("WIN5 は 5 レース必要です。")
    k = [1] * 5
    frontier = [_snapshot(races, k, unit_yen)]
    while math.prod(k) < max_points:
        cur_pts = math.prod(k)
        cur_hit = frontier[-1].hit_prob
        best_i, best_ratio = -1, 0.0
        for i, r in enumerate(races):
            if k[i] >= len(r.horses):
                continue
            cur_cum = r.cum_prob(k[i])
            new_cum = cur_cum + r.horses[k[i]].prob  # 次点を追加
            if cur_cum <= 0:
                continue
            new_hit = cur_hit / cur_cum * new_cum
            new_pts = cur_pts // k[i] * (k[i] + 1)
            d_pts = new_pts - cur_pts
            if d_pts <= 0:
                continue
            ratio = (new_hit - cur_hit) / d_pts
            if ratio > best_ratio:
                best_ratio, best_i = ratio, i
        if best_i < 0:
            break
        k[best_i] += 1
        if math.prod(k) > max_points:
            break
        frontier.append(_snapshot(races, k, unit_yen))
    return frontier


def best_within_budget(
    races: List[Race], budget_yen: int, unit_yen: int = 100
) -> Selection:
    """予算内で的中確率が最大の買い目を返す。"""
    max_points = max(1, budget_yen // unit_yen)
    frontier = optimize_win5(races, max_points=max_points, unit_yen=unit_yen)
    feasible = [s for s in frontier if s.cost_yen <= budget_yen]
    return max(feasible, key=lambda s: s.hit_prob)


def combination_fair_odds(races: List[Race]) -> float:
    """最有力ライン（各レース1番人気）の理論オッズ = 1/Π(最上位勝率)。"""
    p = 1.0
    for r in races:
        p *= r.horses[0].prob
    return (1.0 / p) if p > 0 else float("inf")
