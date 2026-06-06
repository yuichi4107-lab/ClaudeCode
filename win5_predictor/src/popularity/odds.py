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
    prob: float = 0.0  # 補正後の暗黙勝率（β 適用）
    prob_market: float = 0.0  # 市場の暗黙勝率（β=1, 控除率除去のみ）


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
        odds_list = [h.odds for h in horses]
        probs = implied_win_probs(odds_list, beta=beta)
        market = implied_win_probs(odds_list, beta=1.0)
        for h, p, q in zip(horses, probs, market):
            h.prob = float(p)
            h.prob_market = float(q)
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


# ---- 期待値（EV）最大化 ----
#
# パリミューチュエル WIN5 の組合せ C の配当（賭金あたり）は
#   payout(C) ≈ (1 - takeout) / Pmkt(C)
# と近似できる（その組合せに賭けられた割合 ≒ 市場確率 Pmkt(C)=Π q_i）。
# 1 ライン(賭金 unit)の期待値は
#   EV(C) = Ptrue(C)·payout(C) - unit = unit[(1-takeout)·Π(p_i/q_i) - 1]
# β=1 では p=q なので全ライン EV = -unit·takeout（常にマイナス＝妙味なし）。
# β を 1 から動かすと p≠q となり、市場より勝つと見るラインの EV が正に出る。


@dataclass
class EVLine:
    umaban: Sequence[int]
    p_true: float       # Π p_i
    p_market: float     # Π q_i
    payout_yen: float   # 推定配当（unit あたり）
    ev_yen: float       # 1 ライン期待値


@dataclass
class EVPlan:
    takeout: float
    unit_yen: int
    lines: List[EVLine]

    @property
    def points(self) -> int:
        return len(self.lines)

    @property
    def cost_yen(self) -> int:
        return self.points * self.unit_yen

    @property
    def total_ev_yen(self) -> float:
        return sum(l.ev_yen for l in self.lines)

    @property
    def hit_prob(self) -> float:
        return sum(l.p_true for l in self.lines)

    @property
    def expected_roi(self) -> float:
        return (self.total_ev_yen / self.cost_yen) if self.cost_yen else float("nan")


def _line_ev(p_true: float, p_market: float, takeout: float, unit_yen: int) -> tuple[float, float]:
    payout = unit_yen * (1.0 - takeout) / p_market if p_market > 0 else 0.0
    return payout, p_true * payout - unit_yen


def enumerate_ev_lines(
    races: List[Race],
    takeout: float = 0.30,
    unit_yen: int = 100,
    max_per_race: int = 8,
) -> List[EVLine]:
    """各レース上位 max_per_race 頭から作れる全ラインの EV を計算して返す（EV 降順）。"""
    if len(races) != 5:
        raise ValueError("WIN5 は 5 レース必要です。")
    import itertools

    cands = [r.top(min(max_per_race, len(r.horses))) for r in races]
    lines: List[EVLine] = []
    for combo in itertools.product(*cands):
        p_true = 1.0
        p_mkt = 1.0
        for h in combo:
            p_true *= h.prob
            p_mkt *= h.prob_market
        payout, ev = _line_ev(p_true, p_mkt, takeout, unit_yen)
        lines.append(
            EVLine(
                umaban=tuple(h.umaban for h in combo),
                p_true=p_true,
                p_market=p_mkt,
                payout_yen=payout,
                ev_yen=ev,
            )
        )
    lines.sort(key=lambda l: -l.ev_yen)
    return lines


def optimize_win5_ev(
    races: List[Race],
    budget_yen: int,
    takeout: float = 0.30,
    unit_yen: int = 100,
    max_per_race: int = 8,
    positive_only: bool = True,
) -> EVPlan:
    """EV の高いラインから予算内で買う計画を返す。

    positive_only=True なら EV>0 のラインだけを採用する（無ければ「見送り」= 0 ライン）。
    """
    lines = enumerate_ev_lines(races, takeout=takeout, unit_yen=unit_yen, max_per_race=max_per_race)
    max_lines = max(0, budget_yen // unit_yen)
    chosen: List[EVLine] = []
    for l in lines:
        if len(chosen) >= max_lines:
            break
        if positive_only and l.ev_yen <= 0:
            break
        chosen.append(l)
    return EVPlan(takeout=takeout, unit_yen=unit_yen, lines=chosen)
