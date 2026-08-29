"""WIN5 買い目戦略の組み立て。

人気分布モデル（各レースで上位 r 番人気以内に 1 着が入る確率）を使って、
- 5 レース一律に上位 r 番人気を買う「均一戦略」
- 点数（予算）制約のもとで的中確率を最大化する「貪欲フロンティア」
を計算する。

WIN5 は 5 レースの 1 着の組み合わせを 1 点として買う。各レースで r 頭を選ぶと
点数 = r1*r2*...*r5、1 点 100 円なら費用 = 点数 * 100。
"""

from __future__ import annotations

from typing import List

from .model import PopularityModel


def uniform_strategies(
    model: PopularityModel, max_r: int = 6, unit_yen: int = 100
) -> List[dict]:
    """5 レース一律に上位 r 番人気を買う戦略を r=1..max_r で列挙。"""
    out: List[dict] = []
    for r in range(1, max_r + 1):
        p = model.cum_win_prob(r)
        hit = p ** 5
        points = r ** 5
        cost = points * unit_yen
        out.append(
            {
                "r": r,
                "per_race_prob": p,
                "hit_prob": hit,
                "points": points,
                "cost_yen": cost,
                # 損益分岐に必要な払戻（当たった1点で全費用を回収する配当）= 費用 / 的中率
                "breakeven_payout_yen": (cost / hit) if hit > 0 else float("inf"),
            }
        )
    return out


def greedy_budget_frontier(
    model: PopularityModel, max_points: int = 100_000, unit_yen: int = 100
) -> List[dict]:
    """点数制約下で的中確率を最大化する貪欲フロンティア。

    各レースに割り当てる「買う人気の数」 r_i を 1 から開始し、
    1 つ増やしたとき的中確率の伸びがコスト比で最も良いレースを増やしていく。
    レースの分布は同一なので結果はほぼ均一配分になるが、一般化した形で実装する。
    返り値は到達した (点数, 的中確率) のフロンティア各点。
    """
    n_races = 5
    r = [1] * n_races
    # 各レースの上位 r 以内勝率
    def prob(ri: int) -> float:
        return model.cum_win_prob(ri)

    def total_points(rv) -> int:
        pts = 1
        for x in rv:
            pts *= x
        return pts

    def hit_prob(rv) -> float:
        h = 1.0
        for x in rv:
            h *= prob(x)
        return h

    frontier = [
        {
            "points": total_points(r),
            "cost_yen": total_points(r) * unit_yen,
            "hit_prob": hit_prob(r),
            "r_per_race": tuple(r),
        }
    ]
    while total_points(r) < max_points:
        best_i = -1
        best_gain_ratio = 0.0
        cur_hit = hit_prob(r)
        cur_pts = total_points(r)
        for i in range(n_races):
            if r[i] >= model.max_rank:
                continue
            new_r = list(r)
            new_r[i] += 1
            new_hit = hit_prob(new_r)
            new_pts = total_points(new_r)
            d_pts = new_pts - cur_pts
            if d_pts <= 0:
                continue
            gain = (new_hit - cur_hit) / d_pts  # 1 点あたりの的中確率の伸び
            if gain > best_gain_ratio:
                best_gain_ratio = gain
                best_i = i
        if best_i < 0:
            break
        r[best_i] += 1
        if total_points(r) > max_points:
            break
        frontier.append(
            {
                "points": total_points(r),
                "cost_yen": total_points(r) * unit_yen,
                "hit_prob": hit_prob(r),
                "r_per_race": tuple(sorted(r, reverse=True)),
            }
        )
    return frontier
