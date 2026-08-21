"""人気均一戦略のヒストリカル・バックテスト。

「毎回 5 レースとも上位 r 番人気を買う」戦略を過去の WIN5 結果に当てはめ、
的中回数・費用・払戻からおおまかな ROI を見積もる。

注意:
- payout_yen はその回の「正解 1 点」に対する 100 円あたり払戻金。
- 不的中（票数 0）の回は払戻がキャリーオーバーとなり配当不明のため、
  我々の戦略が当たっていたとしても払戻を確定できない（unknown_payout として集計）。
"""

from __future__ import annotations

from typing import List

import numpy as np
import pandas as pd

from .loader import POP_COLS


def backtest_uniform(df: pd.DataFrame, r: int, unit_yen: int = 100) -> dict:
    """上位 r 番人気を毎回全レース買う戦略のバックテスト結果。"""
    points = r ** 5
    cost_per_round = points * unit_yen

    n_rounds = 0
    n_hits = 0
    n_hits_unknown_payout = 0
    total_cost = 0.0
    total_return = 0.0
    per_round: List[dict] = []

    for _, row in df.iterrows():
        pops = [row[c] for c in POP_COLS]
        if any(pd.isna(pops)):
            continue  # 人気未入力の回はスキップ
        pops = [int(x) for x in pops]
        n_rounds += 1
        total_cost += cost_per_round
        hit = all(p <= r for p in pops)
        payout = row["payout_yen"]
        if hit:
            n_hits += 1
            if pd.notna(payout):
                ret = float(payout)  # 正解 1 点ぶんの払戻
                total_return += ret
            else:
                ret = np.nan  # キャリーオーバーで配当不明
                n_hits_unknown_payout += 1
        else:
            ret = 0.0
        per_round.append(
            {
                "date": row["date"],
                "race": row.get("race", ""),
                "pops": pops,
                "hit": hit,
                "payout_yen": (float(payout) if pd.notna(payout) else None),
                "cost_yen": cost_per_round,
                "return_yen": (None if (hit and pd.isna(payout)) else (ret if hit else 0.0)),
            }
        )

    roi = (total_return - total_cost) / total_cost if total_cost > 0 else float("nan")
    return {
        "r": r,
        "points_per_round": points,
        "cost_per_round_yen": cost_per_round,
        "rounds": n_rounds,
        "hits": n_hits,
        "hit_rate": (n_hits / n_rounds) if n_rounds else float("nan"),
        "hits_unknown_payout": n_hits_unknown_payout,
        "total_cost_yen": total_cost,
        "total_return_yen": total_return,
        "profit_yen": total_return - total_cost,
        "roi": roi,
        "per_round": per_round,
    }


def backtest_range(df: pd.DataFrame, max_r: int = 6, unit_yen: int = 100) -> List[dict]:
    """r=1..max_r のバックテスト要約を一覧で返す（per_round は省く）。"""
    out = []
    for r in range(1, max_r + 1):
        res = backtest_uniform(df, r, unit_yen=unit_yen)
        res.pop("per_round", None)
        out.append(res)
    return out
