"""人気-穴バイアス β の較正（最尤推定）。

過去レース群（各レースの全出走馬オッズ＋勝敗）から、
    p_i(β) = q_i^β / Σ_j q_j^β        （q_i = 控除率除去後の市場確率）
の β を、勝ち馬確率の対数尤度を最大化して推定する。

β>1 なら本命を市場より高く評価（人気-穴バイアスの典型）、β<1 ならその逆。
β=1 は「市場（オッズ）をそのまま信じる」。
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import List, Sequence, Tuple

import numpy as np


def _race_devig(odds: Sequence[float]) -> np.ndarray:
    o = np.asarray(odds, dtype=float)
    inv = 1.0 / o
    return inv / inv.sum()


def neg_log_likelihood(beta: float, races_q: List[np.ndarray], winner_idx: List[int]) -> float:
    """β に対する負の対数尤度（小さいほど良い）。"""
    nll = 0.0
    for q, w in zip(races_q, winner_idx):
        pw = np.power(q, beta)
        p = pw / pw.sum()
        nll -= math.log(max(p[w], 1e-12))
    return nll


def fit_beta(
    races: List[Tuple[Sequence[float], int]],
    lo: float = 0.3,
    hi: float = 3.0,
    tol: float = 1e-4,
) -> dict:
    """β を黄金分割探索で最尤推定する。

    races: [(odds_list, winner_index), ...]。winner_index は odds_list 内の勝ち馬位置。
    返り値: {beta, nll, n_races, baseline_nll(β=1)}
    """
    if not races:
        raise ValueError("較正データが空です。")
    races_q = [_race_devig(o) for o, _ in races]
    winner_idx = [w for _, w in races]
    for q, w in zip(races_q, winner_idx):
        if not (0 <= w < len(q)):
            raise ValueError("winner_index が出走頭数の範囲外です。")

    # 黄金分割探索（単峰を仮定）
    gr = (math.sqrt(5) - 1) / 2
    a, b = lo, hi
    c = b - gr * (b - a)
    d = a + gr * (b - a)
    fc = neg_log_likelihood(c, races_q, winner_idx)
    fd = neg_log_likelihood(d, races_q, winner_idx)
    while (b - a) > tol:
        if fc < fd:
            b, d, fd = d, c, fc
            c = b - gr * (b - a)
            fc = neg_log_likelihood(c, races_q, winner_idx)
        else:
            a, c, fc = c, d, fd
            d = a + gr * (b - a)
            fd = neg_log_likelihood(d, races_q, winner_idx)
    beta = (a + b) / 2
    return {
        "beta": beta,
        "nll": neg_log_likelihood(beta, races_q, winner_idx),
        "baseline_nll": neg_log_likelihood(1.0, races_q, winner_idx),
        "n_races": len(races),
    }


def load_history(path: str | Path) -> List[Tuple[List[float], int]]:
    """過去レース CSV を読み込み [(odds_list, winner_index), ...] を返す。

    CSV 列: race_id, odds, won(1/0)。`#` 始まりはコメント。
    各 race_id にちょうど 1 頭 won=1 が必要。
    """
    import pandas as pd

    df = pd.read_csv(path, comment="#")
    df["odds"] = pd.to_numeric(df["odds"], errors="coerce")
    df["won"] = pd.to_numeric(df["won"], errors="coerce").fillna(0).astype(int)
    races: List[Tuple[List[float], int]] = []
    for rid, sub in df.groupby("race_id", sort=False):
        sub = sub.reset_index(drop=True)
        odds = sub["odds"].tolist()
        winners = sub.index[sub["won"] == 1].tolist()
        if len(winners) != 1:
            raise ValueError(f"race_id={rid} の勝ち馬(won=1)が {len(winners)} 頭です（1頭必要）。")
        races.append((odds, int(winners[0])))
    return races
