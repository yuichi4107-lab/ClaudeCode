"""戦略2: マルチコンボ (三連複フォーメーション)"""

import itertools
from typing import List, Tuple

import numpy as np
import pandas as pd

from src.strategies.base_strategy import BaseStrategy, Bet
from src.strategies.bet_sizing import BetSizer


class MultiComboStrategy(BaseStrategy):
    """Multi Combo: 三連複 formation betting.

    Rules:
    - Axis horses: top3_probability >= 0.50 (max 2)
    - Partner horses: top3_probability >= 0.20 (max 5)
    - Max 20 combinations
    - Composite odds >= 15
    - horse_count >= 10
    - 1st favorite probability <= 0.35
    - Bet: 2% of bankroll per race
    """

    def __init__(self, config: dict):
        super().__init__(config)
        cfg = config.get("strategy_2_multi_combo", {})
        self.axis_min_prob = cfg.get("axis_min_top3_probability", 0.50)
        self.partner_min_prob = cfg.get("partner_min_top3_probability", 0.20)
        self.max_axis = cfg.get("max_axis", 2)
        self.max_partners = cfg.get("max_partners", 5)
        self.max_combinations = cfg.get("max_combinations", 20)
        self.min_composite_odds = cfg.get("min_composite_odds", 15.0)
        self.min_horse_count = cfg.get("min_horse_count", 10)
        self.max_favorite_prob = cfg.get("max_favorite_probability", 0.35)
        self.bet_pct = cfg.get("bet_pct", 0.02)
        self.min_bet = config.get("common", {}).get("min_bet", 100)
        self.sizer = BetSizer(min_bet=self.min_bet)

    @property
    def name(self) -> str:
        return "Multi Combo"

    def should_bet(self, race_data: dict, predictions: pd.DataFrame) -> bool:
        """Check if race meets multi combo criteria."""
        if len(predictions) < self.min_horse_count:
            return False
        top_prob = predictions["pred_proba"].max()
        if top_prob > self.max_favorite_prob:
            return False
        return True

    def generate_bets(
        self,
        race_df: pd.DataFrame,
        probas,
        bankroll: float,
    ) -> List[Bet]:
        """Generate 三連複 formation bets."""
        probas = np.asarray(probas)
        if len(race_df) < self.min_horse_count:
            return []

        # Check favorite probability constraint
        if probas.max() > self.max_favorite_prob:
            return []

        # Estimate top-3 probability from win probability
        # Rough heuristic: top3_prob ~ min(1.0, win_prob * 3.5)
        top3_probs = np.minimum(1.0, probas * 3.5)

        horse_nums = []
        for _, row in race_df.iterrows():
            horse_nums.append(int(row.get("horse_number", 0)))

        # Select axis and partner horses
        horse_data = list(zip(horse_nums, probas, top3_probs))
        horse_data.sort(key=lambda x: x[1], reverse=True)  # sort by win prob

        axis_horses = []
        partner_horses = []

        for hnum, wprob, t3prob in horse_data:
            if t3prob >= self.axis_min_prob and len(axis_horses) < self.max_axis:
                axis_horses.append(hnum)
            elif t3prob >= self.partner_min_prob and len(partner_horses) < self.max_partners:
                partner_horses.append(hnum)

        if not axis_horses or len(axis_horses) + len(partner_horses) < 3:
            return []

        # Generate formations
        all_horses = axis_horses + partner_horses
        combinations = self._generate_formations(axis_horses, all_horses)

        if not combinations:
            return []

        # Limit combinations
        combinations = combinations[: self.max_combinations]

        # Check composite odds
        odds_map = {}
        for i, (_, row) in enumerate(race_df.iterrows()):
            hnum = int(row.get("horse_number", 0))
            odds_map[hnum] = row.get("odds", 10.0)

        composite_odds = self._calculate_composite_odds(combinations, odds_map)
        if composite_odds < self.min_composite_odds:
            return []

        # Calculate total bet amount for this race
        total_budget = self.sizer.fixed_percentage(bankroll, self.bet_pct)
        if total_budget <= 0:
            return []

        # Distribute evenly across combinations
        per_combo = max(self.min_bet, int(total_budget / len(combinations) / 100) * 100)

        bets = []
        for combo in combinations:
            sorted_combo = sorted(combo)
            combo_str = "-".join(str(h) for h in sorted_combo)
            bets.append(Bet(
                bet_type="三連複",
                combination=combo_str,
                amount=float(per_combo),
                odds=composite_odds,
                expected_value=0.0,
                horse_numbers=sorted_combo,
            ))

        return bets

    def _generate_formations(
        self,
        axis_horses: List[int],
        all_horses: List[int],
    ) -> List[Tuple[int, ...]]:
        """Generate 三連複 combinations that include at least one axis horse."""
        axis_set = set(axis_horses)
        combos = []
        for combo in itertools.combinations(all_horses, 3):
            if axis_set.intersection(combo):
                combos.append(combo)
        return combos

    def _calculate_composite_odds(
        self,
        combinations: List[Tuple[int, ...]],
        odds_map: dict,
    ) -> float:
        """Estimate composite odds for the formation.

        Uses geometric mean of individual horse odds as a rough proxy.
        """
        if not combinations:
            return 0.0

        combo_odds_list = []
        for combo in combinations:
            individual_odds = [odds_map.get(h, 10.0) for h in combo]
            # Rough 三連複 odds estimate: product of individual odds scaled down
            product = 1.0
            for o in individual_odds:
                product *= o
            combo_odds_list.append(product ** 0.5)  # sqrt for rough scaling

        # Use minimum combo odds as conservative estimate
        return min(combo_odds_list) if combo_odds_list else 0.0
