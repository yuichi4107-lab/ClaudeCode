"""人気順位の経験分布モデル。

各レースの勝ち馬の人気順位 k（1=1番人気）の出現頻度から、
「1着になる馬が k 番人気である確率」 P(win-rank = k) を推定する。

各レースは必ず 1 頭が 1 着になるため、勝ち馬の人気の頻度分布は
そのまま「ランダムに選んだ 1 レースで k 番人気が勝つ確率」の推定量になる。
"""

from __future__ import annotations

from typing import List

import numpy as np


class PopularityModel:
    def __init__(self, max_rank: int = 18):
        self.max_rank = max_rank
        self.p_win_by_rank: np.ndarray | None = None  # index 0..max_rank（0 は未使用）
        self.n_races = 0

    def fit(self, popularities: List[int]) -> "PopularityModel":
        counts = np.zeros(self.max_rank + 1, dtype=float)
        for p in popularities:
            if 1 <= p <= self.max_rank:
                counts[p] += 1.0
        self.n_races = int(counts.sum())
        if self.n_races == 0:
            raise ValueError(
                "人気データが空です。CSV の p1..p5 を入力してから fit してください。"
            )
        self.p_win_by_rank = counts / counts.sum()
        return self

    def _require_fit(self):
        if self.p_win_by_rank is None:
            raise RuntimeError("先に fit() を呼んでください。")

    def win_prob(self, rank: int) -> float:
        """ちょうど rank 番人気が 1 着になる確率。"""
        self._require_fit()
        if rank < 1 or rank > self.max_rank:
            return 0.0
        return float(self.p_win_by_rank[rank])

    def cum_win_prob(self, top_r: int) -> float:
        """1 着馬が「上位 r 番人気以内」に入る確率 P(win-rank <= r)。"""
        self._require_fit()
        top_r = max(0, min(top_r, self.max_rank))
        return float(self.p_win_by_rank[1 : top_r + 1].sum())

    def distribution(self) -> List[dict]:
        """人気順位ごとの勝率と累積勝率の一覧。"""
        self._require_fit()
        rows = []
        cum = 0.0
        for k in range(1, self.max_rank + 1):
            p = float(self.p_win_by_rank[k])
            if p == 0 and cum >= 0.999:
                break
            cum += p
            rows.append({"rank": k, "win_prob": p, "cum_prob": cum})
        return rows
