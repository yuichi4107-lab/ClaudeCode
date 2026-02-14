"""期待値計算

的中確率 × 推定配当 - 購入金額 を基に期待値を算出する。
"""

import logging

import numpy as np

from config.settings import WIN5_BET_UNIT, WIN5_DEDUCTION_RATE
from optimizer.win5_combiner import Win5Combination, Win5Selection, Win5Ticket

logger = logging.getLogger(__name__)


class ExpectedValueCalculator:
    """Win5の期待値を計算する"""

    def __init__(
        self,
        estimated_pool: float = 5_000_000_000,  # 推定発売総額(50億円)
        carryover: float = 0,
    ):
        self.estimated_pool = estimated_pool
        self.carryover = carryover
        self.deduction_rate = WIN5_DEDUCTION_RATE

    def estimate_payout(
        self,
        hit_probability: float,
        pool: float | None = None,
    ) -> float:
        """的中時の推定配当額を計算する

        配当 ≈ (発売総額 × (1 - 控除率) + キャリーオーバー) / 的中票数
        的中票数 ≈ 発売総額 / 100 × hit_probability
        """
        pool = pool or self.estimated_pool

        net_pool = pool * (1.0 - self.deduction_rate) + self.carryover

        # 的中票数の推定
        total_tickets = pool / WIN5_BET_UNIT
        estimated_winners = max(total_tickets * hit_probability, 1.0)

        payout = net_pool / estimated_winners
        return payout

    def calculate_ev(
        self,
        ticket: Win5Ticket,
        pool: float | None = None,
    ) -> dict[str, float]:
        """チケットの期待値を計算する"""
        pool = pool or self.estimated_pool
        hit_prob = ticket.total_hit_probability
        cost = ticket.total_cost

        estimated_payout = self.estimate_payout(hit_prob, pool)

        ev = hit_prob * estimated_payout - cost
        roi = (hit_prob * estimated_payout / cost - 1.0) * 100 if cost > 0 else 0.0

        result = {
            "hit_probability": hit_prob,
            "estimated_payout": estimated_payout,
            "cost": float(cost),
            "expected_value": ev,
            "roi_percent": roi,
            "kelly_edge": hit_prob * (estimated_payout / cost) - 1.0 if cost > 0 else 0.0,
        }

        logger.info(
            "EV: prob=%.4f%%, payout=¥%,.0f, cost=¥%,d, EV=¥%,.0f, ROI=%.1f%%",
            hit_prob * 100,
            estimated_payout,
            cost,
            ev,
            roi,
        )

        return result

    def calculate_combination_evs(
        self,
        combinations: list[Win5Combination],
        pool: float | None = None,
    ) -> list[dict[str, float]]:
        """個別組み合わせの期待値を計算する"""
        pool = pool or self.estimated_pool
        results = []

        for combo in combinations:
            payout = self.estimate_payout(combo.probability, pool)
            ev = combo.probability * payout - combo.cost

            results.append(
                {
                    "horses": combo.horses,
                    "probability": combo.probability,
                    "estimated_payout": payout,
                    "cost": float(combo.cost),
                    "expected_value": ev,
                }
            )

        return results

    def edge_analysis(
        self,
        model_probs: list[float],
        market_probs: list[float],
    ) -> list[dict[str, float]]:
        """モデル予測確率 vs 市場暗示確率のエッジ分析

        Args:
            model_probs: モデルの予測確率(各馬)
            market_probs: オッズから算出した暗示確率(各馬)

        Returns:
            各馬のエッジ情報
        """
        edges = []
        for i, (mp, mkt) in enumerate(zip(model_probs, market_probs)):
            edge = mp - mkt  # 正=過小評価, 負=過大評価
            edge_ratio = mp / mkt if mkt > 0 else 0.0

            edges.append(
                {
                    "index": i,
                    "model_prob": mp,
                    "market_prob": mkt,
                    "edge": edge,
                    "edge_ratio": edge_ratio,
                    "has_value": edge > 0.02,  # 2%以上のエッジ
                }
            )

        return sorted(edges, key=lambda x: x["edge"], reverse=True)
