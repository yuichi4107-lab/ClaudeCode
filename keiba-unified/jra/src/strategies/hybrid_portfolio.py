"""戦略3: ハイブリッドポートフォリオ"""

from typing import List

import numpy as np
import pandas as pd

from src.strategies.base_strategy import BaseStrategy, Bet
from src.strategies.bet_sizing import BetSizer


class HybridPortfolioStrategy(BaseStrategy):
    """Hybrid Portfolio: Combine multiple bet types.

    Allocation: 複勝 40%, 単勝 20%, 馬連 20%, 三連複 20%

    Rules:
    - Race confidence score >= 0.70
    - At least 2 bet types must qualify
    - 3% of bankroll per race
    - Daily loss stop at 10%
    """

    def __init__(self, config: dict):
        super().__init__(config)
        cfg = config.get("strategy_3_hybrid", {})
        self.allocation = cfg.get("allocation", {
            "複勝": 0.40, "単勝": 0.20, "馬連": 0.20, "三連複": 0.20
        })
        self.min_confidence = cfg.get("min_confidence_score", 0.70)
        self.min_active_types = cfg.get("min_active_bet_types", 2)
        self.bet_pct = cfg.get("bet_pct", 0.03)
        self.daily_loss_stop_pct = cfg.get("daily_loss_stop_pct", 0.10)
        self.min_bet = config.get("common", {}).get("min_bet", 100)
        self.initial_bankroll = config.get("common", {}).get("initial_bankroll", 1_000_000)
        self.sizer = BetSizer(min_bet=self.min_bet)

        self.daily_loss = 0.0
        self.daily_investment = 0.0

    @property
    def name(self) -> str:
        return "Hybrid Portfolio"

    def reset_daily(self):
        """Reset daily tracking at start of each day."""
        self.daily_loss = 0.0
        self.daily_investment = 0.0

    def should_bet(self, race_data: dict, predictions: pd.DataFrame) -> bool:
        """Check confidence and daily loss limit."""
        if self.daily_loss >= self.initial_bankroll * self.daily_loss_stop_pct:
            return False
        return True

    def generate_bets(
        self,
        race_df: pd.DataFrame,
        probas,
        bankroll: float,
    ) -> List[Bet]:
        """Generate multi-type portfolio bets."""
        probas = np.asarray(probas)
        if len(race_df) < 8:
            return []

        # Check daily loss limit
        if self.daily_loss >= self.initial_bankroll * self.daily_loss_stop_pct:
            return []

        # Calculate confidence score
        confidence = self._calculate_confidence_score(probas)
        if confidence < self.min_confidence:
            return []

        # Total budget for this race
        total_budget = self.sizer.fixed_percentage(bankroll, self.bet_pct)
        if total_budget <= 0:
            return []

        # Build sorted list of (index, horse_number, prob, odds)
        horses = []
        for i, (idx, row) in enumerate(race_df.iterrows()):
            prob = probas[i] if i < len(probas) else 0.0
            odds = row.get("odds", 0.0)
            hnum = int(row.get("horse_number", i + 1))
            horses.append((hnum, prob, odds))

        horses.sort(key=lambda x: x[1], reverse=True)

        # Generate bets for each type and collect qualifying ones
        all_bets = {}

        place_bets = self._generate_place_bets(horses, total_budget * self.allocation.get("複勝", 0.40))
        if place_bets:
            all_bets["複勝"] = place_bets

        win_bets = self._generate_win_bets(horses, total_budget * self.allocation.get("単勝", 0.20))
        if win_bets:
            all_bets["単勝"] = win_bets

        quinella_bets = self._generate_quinella_bets(horses, total_budget * self.allocation.get("馬連", 0.20))
        if quinella_bets:
            all_bets["馬連"] = quinella_bets

        trifecta_bets = self._generate_trifecta_place_bets(horses, total_budget * self.allocation.get("三連複", 0.20))
        if trifecta_bets:
            all_bets["三連複"] = trifecta_bets

        # Must have at least min_active_types qualifying
        if len(all_bets) < self.min_active_types:
            return []

        # Flatten all bets
        bets = []
        for bet_list in all_bets.values():
            bets.extend(bet_list)

        # Track daily investment
        self.daily_investment += sum(b.amount for b in bets)

        return bets

    def _generate_place_bets(self, horses: list, budget: float) -> List[Bet]:
        """Generate 複勝 bet for top predicted horse."""
        if not horses or budget < self.min_bet:
            return []

        hnum, prob, odds = horses[0]
        if prob < 0.05:
            return []

        amount = max(self.min_bet, int(budget / 100) * 100)
        place_odds = max(1.1, odds * 0.35)
        return [Bet(
            bet_type="複勝",
            combination=str(hnum),
            amount=float(amount),
            odds=place_odds,
            expected_value=prob * place_odds * 2.5,
            horse_numbers=[hnum],
        )]

    def _generate_win_bets(self, horses: list, budget: float) -> List[Bet]:
        """Generate 単勝 bet using value betting logic."""
        if not horses or budget < self.min_bet:
            return []

        hnum, prob, odds = horses[0]
        if prob < 0.08 or odds < 2.0:
            return []

        ev = prob * odds
        if ev < 1.10:
            return []

        amount = max(self.min_bet, int(budget / 100) * 100)
        return [Bet(
            bet_type="単勝",
            combination=str(hnum),
            amount=float(amount),
            odds=odds,
            expected_value=ev,
            horse_numbers=[hnum],
        )]

    def _generate_quinella_bets(self, horses: list, budget: float) -> List[Bet]:
        """Generate 馬連 bet for top 2 predicted horses."""
        if len(horses) < 2 or budget < self.min_bet:
            return []

        h1_num, h1_prob, h1_odds = horses[0]
        h2_num, h2_prob, h2_odds = horses[1]

        if h1_prob < 0.10 or h2_prob < 0.08:
            return []

        combo = sorted([h1_num, h2_num])
        combo_str = f"{combo[0]}-{combo[1]}"
        estimated_odds = max(2.0, (h1_odds * h2_odds) ** 0.5)

        amount = max(self.min_bet, int(budget / 100) * 100)
        return [Bet(
            bet_type="馬連",
            combination=combo_str,
            amount=float(amount),
            odds=estimated_odds,
            expected_value=h1_prob * h2_prob * estimated_odds * 10,
            horse_numbers=combo,
        )]

    def _generate_trifecta_place_bets(self, horses: list, budget: float) -> List[Bet]:
        """Generate 三連複 bet for top 3 predicted horses."""
        if len(horses) < 3 or budget < self.min_bet:
            return []

        h1_num, h1_prob, _ = horses[0]
        h2_num, h2_prob, _ = horses[1]
        h3_num, h3_prob, _ = horses[2]

        if h1_prob < 0.10 or h2_prob < 0.08 or h3_prob < 0.05:
            return []

        combo = sorted([h1_num, h2_num, h3_num])
        combo_str = f"{combo[0]}-{combo[1]}-{combo[2]}"

        # Rough odds estimate
        all_odds = []
        for h in horses[:3]:
            all_odds.append(h[2])
        estimated_odds = max(5.0, np.prod(all_odds) ** 0.4)

        amount = max(self.min_bet, int(budget / 100) * 100)
        return [Bet(
            bet_type="三連複",
            combination=combo_str,
            amount=float(amount),
            odds=estimated_odds,
            expected_value=0.0,
            horse_numbers=combo,
        )]

    def _calculate_confidence_score(self, probas: np.ndarray) -> float:
        """Confidence = sum of top-3 horses probabilities / 0.90."""
        sorted_probs = np.sort(probas)[::-1]
        top3_sum = sorted_probs[:3].sum() if len(sorted_probs) >= 3 else sorted_probs.sum()
        return float(top3_sum / 0.90)
