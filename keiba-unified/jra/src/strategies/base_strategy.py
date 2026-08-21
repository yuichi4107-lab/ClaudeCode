"""ベッティング戦略の抽象基底クラス"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List

import pandas as pd


@dataclass
class Bet:
    """A single bet to be placed."""

    race_id: str = ""
    race_date: str = ""
    bet_type: str = ""          # 単勝, 複勝, 馬連, ワイド, 三連複, 三連単
    combination: str = ""       # e.g. "3" or "3-7" or "3-7-12"
    amount: float = 0.0        # yen
    odds: float = 0.0          # expected odds
    expected_value: float = 0.0
    horse_numbers: List[int] = field(default_factory=list)
    payout: float = 0.0
    profit: float = 0.0
    is_hit: bool = False


class BaseStrategy(ABC):
    """Abstract base class for betting strategies."""

    def __init__(self, config: dict):
        self.config = config
        self.common = config.get("common", {})

    @abstractmethod
    def should_bet(self, race_data: dict, predictions: pd.DataFrame) -> bool:
        """Determine if this race is worth betting on."""

    @abstractmethod
    def generate_bets(
        self,
        race_df: pd.DataFrame,
        probas,
        bankroll: float,
    ) -> List[Bet]:
        """Generate list of bets for a race.

        Args:
            race_df: DataFrame with race horse data for one race.
            probas: Model predicted probabilities (array-like).
            bankroll: Current bankroll in yen.

        Returns:
            List of Bet objects. Each Bet will be converted to a BetRecord
            by the backtest engine.
        """

    @property
    @abstractmethod
    def name(self) -> str:
        """Strategy name."""
