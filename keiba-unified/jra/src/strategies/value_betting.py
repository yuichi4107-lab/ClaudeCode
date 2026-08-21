"""戦略1: バリューベッティング (単勝/複勝)"""

from typing import List

import numpy as np
import pandas as pd

from src.strategies.base_strategy import BaseStrategy, Bet
from src.strategies.bet_sizing import BetSizer


class ValueBettingStrategy(BaseStrategy):
    """Value Betting: Buy 単勝/複勝 when expected value exceeds threshold.

    Rules:
    - expected_value = model_prob * odds >= 1.25
    - model_prob >= 0.08
    - odds in [2.0, 50.0]
    - horse_count >= 8
    - Max 3 horses per race
    - 単勝: EV >= 1.30
    - 複勝: EV >= 1.15
    - Bet sizing: Fractional Kelly 25%, max 5% of bankroll
    """

    def __init__(self, config: dict):
        super().__init__(config)
        cfg = config.get("strategy_1_value_betting", {})
        self.min_ev = cfg.get("min_expected_value", 1.25)
        self.min_prob = cfg.get("min_model_probability", 0.08)
        self.odds_min, self.odds_max = cfg.get("odds_range", [2.0, 50.0])
        self.min_horse_count = cfg.get("min_horse_count", 8)
        self.max_targets = cfg.get("max_targets_per_race", 3)
        self.kelly_fraction = cfg.get("kelly_fraction", 0.25)
        self.max_bet_pct = cfg.get("max_bet_pct", 0.05)
        self.win_ev_threshold = cfg.get("win_ev_threshold", 1.30)
        self.place_ev_threshold = cfg.get("place_ev_threshold", 1.15)
        self.min_bet = config.get("common", {}).get("min_bet", 100)
        self.sizer = BetSizer(min_bet=self.min_bet)

    @property
    def name(self) -> str:
        return "Value Betting"

    def should_bet(self, race_data: dict, predictions: pd.DataFrame) -> bool:
        """Check if any horse meets EV threshold."""
        if len(predictions) < self.min_horse_count:
            return False
        for _, row in predictions.iterrows():
            prob = row.get("pred_proba", 0.0)
            odds = row.get("odds", 0.0)
            if prob < self.min_prob:
                continue
            if not (self.odds_min <= odds <= self.odds_max):
                continue
            ev = prob * odds
            if ev >= self.min_ev:
                return True
        return False

    def generate_bets(
        self,
        race_df: pd.DataFrame,
        probas,
        bankroll: float,
    ) -> List[Bet]:
        """Generate 単勝 and 複勝 bets for qualifying horses."""
        probas = np.asarray(probas)
        if len(race_df) < self.min_horse_count:
            return []

        bets = []
        candidates = []

        for i, (idx, row) in enumerate(race_df.iterrows()):
            prob = probas[i] if i < len(probas) else 0.0
            odds = row.get("odds", 0.0)
            horse_num = int(row.get("horse_number", i + 1))

            if prob < self.min_prob:
                continue
            if not (self.odds_min <= odds <= self.odds_max):
                continue

            ev = prob * odds
            if ev >= self.min_ev:
                candidates.append((ev, prob, odds, horse_num))

        # Sort by EV descending, take top N
        candidates.sort(key=lambda x: x[0], reverse=True)
        candidates = candidates[: self.max_targets]

        for ev, prob, odds, horse_num in candidates:
            combo_str = str(horse_num)

            # 単勝 bet
            if ev >= self.win_ev_threshold:
                amount = self.sizer.calculate_bet_amount(
                    bankroll, prob, odds,
                    kelly_fraction=self.kelly_fraction,
                    max_bet_pct=self.max_bet_pct,
                )
                if amount > 0:
                    bets.append(Bet(
                        bet_type="単勝",
                        combination=combo_str,
                        amount=amount,
                        odds=odds,
                        expected_value=ev,
                        horse_numbers=[horse_num],
                    ))

            # 複勝 bet (use ~1/3 of odds as estimate for place odds)
            place_odds = max(1.1, odds * 0.35)
            place_ev = prob * place_odds * 2.5  # rough top-3 probability scaling
            if place_ev >= self.place_ev_threshold:
                amount = self.sizer.calculate_bet_amount(
                    bankroll, min(prob * 2.5, 0.95), place_odds,
                    kelly_fraction=self.kelly_fraction,
                    max_bet_pct=self.max_bet_pct,
                )
                if amount > 0:
                    bets.append(Bet(
                        bet_type="複勝",
                        combination=combo_str,
                        amount=amount,
                        odds=place_odds,
                        expected_value=place_ev,
                        horse_numbers=[horse_num],
                    ))

        return bets
