"""予算制約下での最適買い目選択

全有効割当 (n1 × n2 × n3 × n4 × n5 ≤ budget / 100) を列挙し、
的中確率を最大化する組み合わせを選択する。
"""

import itertools
import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

from config.settings import DEFAULT_BUDGET, WIN5_BET_UNIT, WIN5_NUM_RACES
from optimizer.win5_combiner import Win5Combiner, Win5Selection, Win5Ticket

logger = logging.getLogger(__name__)


@dataclass
class BudgetAllocation:
    """各レースの選択頭数の割り当て"""

    allocation: tuple[int, ...]  # (n1, n2, n3, n4, n5)
    num_combinations: int
    total_cost: int
    hit_probability: float


class BudgetOptimizer:
    """予算制約下でWin5の最適な買い目を決定する"""

    def __init__(self, combiner: Win5Combiner, budget: int = DEFAULT_BUDGET):
        self.combiner = combiner
        self.budget = budget
        self.max_combos = budget // WIN5_BET_UNIT

    def find_optimal_allocation(
        self, max_per_race: int = 8
    ) -> BudgetAllocation | None:
        """予算内で的中確率を最大化する頭数割り当てを探索する"""
        n_races = len(self.combiner.race_ids)
        if n_races == 0:
            return None

        # 各レースで選択可能な頭数の上限
        max_per = min(max_per_race, self.max_combos)

        best: BudgetAllocation | None = None

        # 全割り当てパターンを列挙(制約: 積 ≤ max_combos)
        ranges = [range(1, max_per + 1) for _ in range(n_races)]

        for alloc in itertools.product(*ranges):
            n_combos = 1
            for n in alloc:
                n_combos *= n
                if n_combos > self.max_combos:
                    break

            if n_combos > self.max_combos:
                continue

            # この割り当てでの的中確率を計算
            selections = self._make_selections(alloc)
            hit_prob = self.combiner.calculate_hit_probability(selections)

            cost = n_combos * WIN5_BET_UNIT
            candidate = BudgetAllocation(
                allocation=alloc,
                num_combinations=n_combos,
                total_cost=cost,
                hit_probability=hit_prob,
            )

            if best is None or candidate.hit_probability > best.hit_probability:
                best = candidate

        if best:
            logger.info(
                "Optimal allocation: %s (combos=%d, cost=¥%d, prob=%.4f%%)",
                best.allocation,
                best.num_combinations,
                best.total_cost,
                best.hit_probability * 100,
            )

        return best

    def find_top_allocations(
        self, max_per_race: int = 8, top_n: int = 10
    ) -> list[BudgetAllocation]:
        """的中確率上位N個の割り当てを返す"""
        n_races = len(self.combiner.race_ids)
        if n_races == 0:
            return []

        max_per = min(max_per_race, self.max_combos)
        results: list[BudgetAllocation] = []

        ranges = [range(1, max_per + 1) for _ in range(n_races)]

        for alloc in itertools.product(*ranges):
            n_combos = 1
            for n in alloc:
                n_combos *= n
                if n_combos > self.max_combos:
                    break

            if n_combos > self.max_combos:
                continue

            selections = self._make_selections(alloc)
            hit_prob = self.combiner.calculate_hit_probability(selections)
            cost = n_combos * WIN5_BET_UNIT

            results.append(
                BudgetAllocation(
                    allocation=alloc,
                    num_combinations=n_combos,
                    total_cost=cost,
                    hit_probability=hit_prob,
                )
            )

        results.sort(key=lambda x: x.hit_probability, reverse=True)
        return results[:top_n]

    def optimize(self, max_per_race: int = 8) -> Win5Ticket | None:
        """最適な買い目チケットを生成する"""
        best_alloc = self.find_optimal_allocation(max_per_race)
        if best_alloc is None:
            return None

        selections = self._make_selections(best_alloc.allocation)
        ticket = self.combiner.build_ticket(selections)
        return ticket

    def _make_selections(self, allocation: tuple[int, ...]) -> list[Win5Selection]:
        """割り当てに基づいて各レースのtop N馬を選択する"""
        selections = []
        for i, (race_id, n_horses) in enumerate(
            zip(self.combiner.race_ids, allocation)
        ):
            pred_df = self.combiner.predictions[race_id]
            if pred_df.empty:
                continue

            top = pred_df.nlargest(n_horses, "calibrated_prob")

            sel = Win5Selection(
                race_id=race_id,
                race_number=i + 1,
                horse_numbers=top["horse_number"].tolist(),
                horse_names=top["horse_name"].tolist() if "horse_name" in top.columns else [],
                probabilities=top["calibrated_prob"].tolist(),
            )
            selections.append(sel)

        return selections
