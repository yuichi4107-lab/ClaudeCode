"""戦略4: アップセットハンター (穴馬狙い)"""

from typing import List, Tuple

import numpy as np
import pandas as pd

from src.strategies.base_strategy import BaseStrategy, Bet
from src.strategies.bet_sizing import BetSizer


class UpsetHunterStrategy(BaseStrategy):
    """Upset Hunter: Target undervalued long-shot horses.

    Target horse criteria:
    - popularity >= 6 (6th or lower favorite)
    - odds >= 10.0
    - model_prob / implied_prob >= 2.0
    - top3_probability >= 0.20

    Race criteria:
    - Favorite odds >= 2.5
    - horse_count >= 12
    - Max 5 races per day

    Bets: 単勝 30%, 複勝 30%, ワイド 40%
    Amount: 1% of bankroll per race
    """

    def __init__(self, config: dict):
        super().__init__(config)
        cfg = config.get("strategy_4_upset_hunter", {})
        self.min_popularity_rank = cfg.get("min_popularity_rank", 6)
        self.min_odds = cfg.get("min_odds", 10.0)
        self.model_vs_market_ratio = cfg.get("model_vs_market_ratio", 2.0)
        self.min_top3_prob = cfg.get("min_top3_probability", 0.20)
        self.min_favorite_odds = cfg.get("min_favorite_odds", 2.5)
        self.min_horse_count = cfg.get("min_horse_count", 12)
        self.max_races_per_day = cfg.get("max_races_per_day", 5)
        self.bet_pct = cfg.get("bet_pct", 0.01)
        self.allocation = cfg.get("allocation", {
            "単勝": 0.30, "複勝": 0.30, "ワイド": 0.40
        })
        self.min_bet = config.get("common", {}).get("min_bet", 100)
        self.sizer = BetSizer(min_bet=self.min_bet)

        self.daily_race_count = 0

    @property
    def name(self) -> str:
        return "Upset Hunter"

    def reset_daily(self):
        """Reset daily tracking."""
        self.daily_race_count = 0

    def should_bet(self, race_data: dict, predictions: pd.DataFrame) -> bool:
        """Check race-level criteria."""
        if self.daily_race_count >= self.max_races_per_day:
            return False
        return True

    def generate_bets(
        self,
        race_df: pd.DataFrame,
        probas,
        bankroll: float,
    ) -> List[Bet]:
        """Generate upset-targeting bets."""
        probas = np.asarray(probas)
        if len(race_df) < self.min_horse_count:
            return []

        if self.daily_race_count >= self.max_races_per_day:
            return []

        # Build horse list with odds and probabilities
        horses = []
        for i, (idx, row) in enumerate(race_df.iterrows()):
            prob = probas[i] if i < len(probas) else 0.0
            odds = row.get("odds", 0.0)
            hnum = int(row.get("horse_number", i + 1))
            popularity = row.get("popularity", i + 1)
            horses.append((hnum, prob, odds, int(popularity)))

        # Check favorite odds (lowest odds horse)
        odds_sorted = sorted(horses, key=lambda x: x[2])
        if odds_sorted and odds_sorted[0][2] < self.min_favorite_odds:
            return []

        # Find upset candidates
        upset_candidates = self._find_upset_candidates(horses)
        if not upset_candidates:
            return []

        # Use the best upset candidate
        best = upset_candidates[0]
        upset_hnum, upset_prob, upset_odds = best

        # Get favorites (top 3 by probability)
        prob_sorted = sorted(horses, key=lambda x: x[1], reverse=True)
        favorites = [(h[0], h[1], h[2]) for h in prob_sorted[:3]]

        # Calculate total budget
        total_budget = self.sizer.fixed_percentage(bankroll, self.bet_pct)
        if total_budget <= 0:
            return []

        bets = []

        # 単勝 30%
        win_budget = total_budget * self.allocation.get("単勝", 0.30)
        win_amount = max(self.min_bet, int(win_budget / 100) * 100)
        if win_amount >= self.min_bet:
            bets.append(Bet(
                bet_type="単勝",
                combination=str(upset_hnum),
                amount=float(win_amount),
                odds=upset_odds,
                expected_value=upset_prob * upset_odds,
                horse_numbers=[upset_hnum],
            ))

        # 複勝 30%
        place_budget = total_budget * self.allocation.get("複勝", 0.30)
        place_amount = max(self.min_bet, int(place_budget / 100) * 100)
        place_odds = max(1.5, upset_odds * 0.3)
        if place_amount >= self.min_bet:
            bets.append(Bet(
                bet_type="複勝",
                combination=str(upset_hnum),
                amount=float(place_amount),
                odds=place_odds,
                expected_value=upset_prob * place_odds * 2.5,
                horse_numbers=[upset_hnum],
            ))

        # ワイド 40%: upset horse with each of top-3 favorites
        wide_bets = self._generate_wide_bets(
            (upset_hnum, upset_prob, upset_odds),
            favorites,
            total_budget * self.allocation.get("ワイド", 0.40),
        )
        bets.extend(wide_bets)

        if bets:
            self.daily_race_count += 1

        return bets

    def _find_upset_candidates(
        self, horses: List[Tuple]
    ) -> List[Tuple[int, float, float]]:
        """Find horses meeting upset criteria.

        Returns:
            List of (horse_number, prob, odds) sorted by model/market ratio desc.
        """
        candidates = []
        for hnum, prob, odds, popularity in horses:
            if odds <= 0:
                continue

            # Popularity check (6th or lower favorite)
            if popularity < self.min_popularity_rank:
                continue

            # Odds check
            if odds < self.min_odds:
                continue

            # Model vs market ratio
            implied_prob = 1.0 / odds if odds > 0 else 0.0
            if implied_prob <= 0:
                continue
            ratio = prob / implied_prob
            if ratio < self.model_vs_market_ratio:
                continue

            # Top-3 probability estimate
            top3_prob = min(1.0, prob * 3.5)
            if top3_prob < self.min_top3_prob:
                continue

            candidates.append((hnum, prob, odds, ratio))

        # Sort by model/market ratio descending
        candidates.sort(key=lambda x: x[3], reverse=True)
        return [(c[0], c[1], c[2]) for c in candidates]

    def _generate_wide_bets(
        self,
        upset_horse: Tuple[int, float, float],
        favorites: List[Tuple[int, float, float]],
        budget: float,
    ) -> List[Bet]:
        """Generate ワイド bets: upset horse with each of top-3 favorites."""
        upset_hnum, upset_prob, upset_odds = upset_horse
        bets = []

        valid_favorites = [f for f in favorites if f[0] != upset_hnum]
        if not valid_favorites:
            return []

        per_bet_budget = budget / len(valid_favorites)

        for fav_hnum, fav_prob, fav_odds in valid_favorites:
            amount = max(self.min_bet, int(per_bet_budget / 100) * 100)
            if amount < self.min_bet:
                continue

            combo = sorted([upset_hnum, fav_hnum])
            combo_str = f"{combo[0]}-{combo[1]}"
            # Rough ワイド odds estimate
            wide_odds = max(2.0, (upset_odds * fav_odds) ** 0.35)

            bets.append(Bet(
                bet_type="ワイド",
                combination=combo_str,
                amount=float(amount),
                odds=wide_odds,
                expected_value=0.0,
                horse_numbers=combo,
            ))

        return bets
