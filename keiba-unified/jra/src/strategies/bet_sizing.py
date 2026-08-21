"""ベットサイジングモジュール (Kelly Criterion)"""

import math


class BetSizer:
    """Calculate optimal bet amounts using Kelly Criterion and variants."""

    def __init__(self, min_bet: float = 100):
        self.min_bet = min_bet

    def kelly_criterion(self, win_prob: float, odds: float) -> float:
        """Full Kelly fraction.

        f* = (b * p - q) / b
        where b = odds - 1, p = win_prob, q = 1 - p.

        Returns:
            Fraction of bankroll to bet (0.0 if negative edge).
        """
        if odds <= 1.0 or win_prob <= 0.0 or win_prob >= 1.0:
            return 0.0
        b = odds - 1.0
        p = win_prob
        q = 1.0 - p
        f = (b * p - q) / b
        return max(0.0, f)

    def fractional_kelly(
        self, win_prob: float, odds: float, fraction: float = 0.25
    ) -> float:
        """Apply Kelly fraction (e.g., 25% Kelly).

        Returns:
            Fraction of bankroll to bet.
        """
        return self.kelly_criterion(win_prob, odds) * fraction

    def calculate_bet_amount(
        self,
        bankroll: float,
        win_prob: float,
        odds: float,
        kelly_fraction: float = 0.25,
        max_bet_pct: float = 0.05,
    ) -> float:
        """Calculate bet amount in yen.

        1. Compute fractional Kelly fraction.
        2. bet = bankroll * fraction.
        3. Clamp to [min_bet, bankroll * max_bet_pct].
        4. Round down to nearest 100 yen.

        Returns:
            Bet amount in yen, or 0.0 if below min_bet.
        """
        frac = self.fractional_kelly(win_prob, odds, kelly_fraction)
        if frac <= 0.0:
            return 0.0

        bet = bankroll * frac
        max_bet = bankroll * max_bet_pct
        bet = min(bet, max_bet)

        # Round down to nearest 100 yen
        bet = math.floor(bet / 100) * 100

        if bet < self.min_bet:
            return 0.0
        return float(bet)

    def fixed_percentage(self, bankroll: float, pct: float) -> float:
        """Fixed percentage of bankroll, rounded to 100 yen.

        Returns:
            Bet amount in yen.
        """
        bet = bankroll * pct
        bet = math.floor(bet / 100) * 100
        if bet < self.min_bet:
            return 0.0
        return float(bet)
