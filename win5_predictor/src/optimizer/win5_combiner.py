"""Win5 買い目組み合わせ生成

5レース各々の候補馬から全組み合わせを列挙する。
"""

import itertools
import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

from config.settings import WIN5_BET_UNIT, WIN5_NUM_RACES

logger = logging.getLogger(__name__)


@dataclass
class Win5Selection:
    """Win5の1レース分の選択"""

    race_id: str
    race_number: int
    horse_numbers: list[int]
    horse_names: list[str]
    probabilities: list[float]  # 各馬の勝利確率


@dataclass
class Win5Combination:
    """Win5の1組合せ"""

    horses: tuple[int, ...]  # (R1馬番, R2馬番, R3馬番, R4馬番, R5馬番)
    probability: float  # 的中確率(各レース独立と仮定)
    cost: int = WIN5_BET_UNIT


@dataclass
class Win5Ticket:
    """Win5の購入チケット(選択セット)"""

    selections: list[Win5Selection]  # 5レース分
    num_combinations: int
    total_cost: int
    total_hit_probability: float
    expected_value: float = 0.0


class Win5Combiner:
    """Win5の買い目を生成する"""

    def __init__(self, predictions: dict[str, pd.DataFrame]):
        """
        Args:
            predictions: {race_id: DataFrame(horse_number, calibrated_prob, ...)}
        """
        self.predictions = predictions
        self.race_ids = list(predictions.keys())

        if len(self.race_ids) != WIN5_NUM_RACES:
            logger.warning(
                "Expected %d races, got %d", WIN5_NUM_RACES, len(self.race_ids)
            )

    def generate_selections(
        self,
        max_horses_per_race: int = 5,
        prob_threshold: float = 0.0,
    ) -> list[Win5Selection]:
        """各レースの候補馬を選定する"""
        selections = []

        for i, race_id in enumerate(self.race_ids):
            pred_df = self.predictions[race_id]
            if pred_df.empty:
                logger.warning("No predictions for race %s", race_id)
                continue

            # 確率順でtop N
            top = pred_df.nlargest(max_horses_per_race, "calibrated_prob")

            if prob_threshold > 0:
                top = top[top["calibrated_prob"] >= prob_threshold]

            if top.empty:
                top = pred_df.nlargest(1, "calibrated_prob")

            sel = Win5Selection(
                race_id=race_id,
                race_number=i + 1,
                horse_numbers=top["horse_number"].tolist(),
                horse_names=top["horse_name"].tolist() if "horse_name" in top.columns else [],
                probabilities=top["calibrated_prob"].tolist(),
            )
            selections.append(sel)

        return selections

    def count_combinations(self, selections: list[Win5Selection]) -> int:
        """組み合わせ数を計算する"""
        if not selections:
            return 0
        total = 1
        for sel in selections:
            total *= len(sel.horse_numbers)
        return total

    def calculate_hit_probability(self, selections: list[Win5Selection]) -> float:
        """的中確率を計算する(各レース独立、少なくとも1頭的中する確率の積)"""
        if len(selections) < WIN5_NUM_RACES:
            return 0.0

        prob = 1.0
        for sel in selections:
            race_prob = sum(sel.probabilities)
            prob *= min(race_prob, 1.0)
        return prob

    def enumerate_all_combinations(
        self, selections: list[Win5Selection]
    ) -> list[Win5Combination]:
        """全組み合わせを列挙する(注: 大量になりうるので注意)"""
        if not selections:
            return []

        horse_lists = []
        prob_lists = []
        for sel in selections:
            horse_lists.append(sel.horse_numbers)
            prob_dict = dict(zip(sel.horse_numbers, sel.probabilities))
            prob_lists.append(prob_dict)

        combos = []
        for combo in itertools.product(*horse_lists):
            prob = 1.0
            for i, horse_num in enumerate(combo):
                prob *= prob_lists[i].get(horse_num, 0.0)
            combos.append(Win5Combination(horses=combo, probability=prob))

        combos.sort(key=lambda c: c.probability, reverse=True)
        return combos

    def build_ticket(
        self, selections: list[Win5Selection]
    ) -> Win5Ticket:
        """Win5購入チケットを生成する"""
        n_combos = self.count_combinations(selections)
        hit_prob = self.calculate_hit_probability(selections)

        return Win5Ticket(
            selections=selections,
            num_combinations=n_combos,
            total_cost=n_combos * WIN5_BET_UNIT,
            total_hit_probability=hit_prob,
        )

    def format_selections(self, selections: list[Win5Selection]) -> str:
        """選択を表示用にフォーマットする"""
        lines = []
        for sel in selections:
            names = ", ".join(
                f"{n}({p:.1%})"
                for n, p in zip(sel.horse_numbers, sel.probabilities)
            )
            horse_names_str = ""
            if sel.horse_names:
                horse_names_str = " / " + ", ".join(sel.horse_names)
            lines.append(f"  Race{sel.race_number} [{sel.race_id}]: {names}{horse_names_str}")

        n_combos = self.count_combinations(selections)
        hit_prob = self.calculate_hit_probability(selections)
        lines.append(f"  ---")
        lines.append(f"  組合せ数: {n_combos}")
        lines.append(f"  購入金額: ¥{n_combos * WIN5_BET_UNIT:,}")
        lines.append(f"  的中確率: {hit_prob:.4%}")

        return "\n".join(lines)
