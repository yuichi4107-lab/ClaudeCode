"""バックテストエンジン"""

from dataclasses import dataclass, field
from typing import List

import numpy as np
import pandas as pd

from src.utils.logger import setup_logger

logger = setup_logger(__name__)


@dataclass
class BetRecord:
    """Single bet record."""

    race_id: str
    race_date: str
    bet_type: str
    combination: str
    amount: float
    odds: float
    payout: float
    profit: float
    is_hit: bool


@dataclass
class BacktestResult:
    """Aggregated backtest results."""

    bets: List[BetRecord] = field(default_factory=list)
    equity_curve: pd.Series = None
    daily_returns: pd.Series = None
    total_investment: float = 0.0
    total_payout: float = 0.0

    @property
    def roi(self) -> float:
        if self.total_investment == 0:
            return 0.0
        return self.total_payout / self.total_investment * 100

    @property
    def net_profit(self) -> float:
        return self.total_payout - self.total_investment

    @property
    def total_bets(self) -> int:
        return len(self.bets)

    @property
    def winning_bets(self) -> int:
        return sum(1 for b in self.bets if b.is_hit)

    @property
    def hit_rate(self) -> float:
        if self.total_bets == 0:
            return 0.0
        return self.winning_bets / self.total_bets * 100

    def merge(self, other: "BacktestResult") -> "BacktestResult":
        """Merge another BacktestResult into this one."""
        merged = BacktestResult()
        merged.bets = self.bets + other.bets
        merged.total_investment = self.total_investment + other.total_investment
        merged.total_payout = self.total_payout + other.total_payout

        # Merge equity curves
        curves = [
            c
            for c in [self.equity_curve, other.equity_curve]
            if c is not None
        ]
        if curves:
            merged.equity_curve = pd.concat(curves).sort_index()

        # Merge daily returns
        rets = [
            r
            for r in [self.daily_returns, other.daily_returns]
            if r is not None
        ]
        if rets:
            merged.daily_returns = pd.concat(rets).sort_index()

        return merged


class BacktestEngine:
    """Core backtest engine that runs a single train/test window."""

    def __init__(self, initial_bankroll: float = 1_000_000):
        self.initial_bankroll = initial_bankroll

    def run(
        self,
        features_df: pd.DataFrame,
        results_df: pd.DataFrame,
        payoffs_df: pd.DataFrame,
        strategy,
        model,
        train_idx: pd.Index,
        test_idx: pd.Index,
    ) -> BacktestResult:
        """Run backtest for one time window.

        Args:
            features_df: Feature matrix. Must contain 'race_id' and 'race_date'
                columns, plus all model input features.
            results_df: Race results with columns: race_id, horse_number,
                finish_position, etc.
            payoffs_df: Payout data with columns: race_id, bet_type,
                combination, payout_amount.
            strategy: Strategy object with generate_bets(race_df, probas, bankroll).
            model: BaseModel instance.
            train_idx: Index for training rows.
            test_idx: Index for test rows.

        Returns:
            BacktestResult for this window.
        """
        # Identify feature columns (exclude metadata)
        meta_cols = {"race_id", "race_date", "horse_number", "horse_id",
                     "finish_position", "target"}
        feature_cols = [
            c for c in features_df.columns if c not in meta_cols
        ]

        # Train
        X_train = features_df.loc[train_idx, feature_cols]
        y_train = features_df.loc[train_idx, "target"]
        model.fit(X_train, y_train)

        # Predict
        X_test = features_df.loc[test_idx, feature_cols]
        probas = model.predict_proba(X_test)

        test_df = features_df.loc[test_idx].copy()
        test_df["pred_proba"] = probas

        # Generate bets race by race
        result = BacktestResult()
        bankroll = self.initial_bankroll
        daily_pnl = {}

        race_ids = test_df["race_id"].unique()
        for race_id in race_ids:
            race_mask = test_df["race_id"] == race_id
            race_df = test_df[race_mask]
            race_probas = race_df["pred_proba"].values
            race_date = str(race_df["race_date"].iloc[0])

            bets = strategy.generate_bets(race_df, race_probas, bankroll)
            if not bets:
                continue

            for bet in bets:
                bet.race_id = race_id
                bet.race_date = race_date

                # Check hit and look up payout
                bet.is_hit = self._check_hit(bet, results_df)
                if bet.is_hit:
                    bet.payout = self._calculate_payout(bet, payoffs_df)
                else:
                    bet.payout = 0.0
                bet.profit = bet.payout - bet.amount

                result.bets.append(bet)
                result.total_investment += bet.amount
                result.total_payout += bet.payout
                bankroll += bet.profit

                # Accumulate daily P&L
                if race_date not in daily_pnl:
                    daily_pnl[race_date] = 0.0
                daily_pnl[race_date] += bet.profit

        # Build equity curve and daily returns
        if daily_pnl:
            sorted_dates = sorted(daily_pnl.keys())
            equity = self.initial_bankroll
            eq_values = {}
            ret_values = {}
            for d in sorted_dates:
                equity += daily_pnl[d]
                eq_values[d] = equity
                ret_values[d] = daily_pnl[d]

            result.equity_curve = pd.Series(eq_values, name="equity")
            result.equity_curve.index = pd.to_datetime(result.equity_curve.index)
            result.daily_returns = pd.Series(ret_values, name="daily_return")
            result.daily_returns.index = pd.to_datetime(result.daily_returns.index)

        return result

    def _calculate_payout(
        self, bet: BetRecord, payoffs_df: pd.DataFrame
    ) -> float:
        """Look up actual payout for a winning bet from payoffs data."""
        # Normalize combination: remove spaces around separators
        bet_combo_normalized = bet.combination.replace(" ", "")

        race_payoffs = payoffs_df[
            (payoffs_df["race_id"] == bet.race_id)
            & (payoffs_df["bet_type"] == bet.bet_type)
        ]

        if race_payoffs.empty:
            return bet.amount * bet.odds

        # Try exact match first, then normalized match
        matched = race_payoffs[race_payoffs["combination"] == bet.combination]
        if matched.empty:
            # Normalize DB combinations for comparison
            normalized = race_payoffs["combination"].str.replace(" ", "", regex=False)
            matched = race_payoffs[normalized == bet_combo_normalized]

        if matched.empty:
            return bet.amount * bet.odds

        payout_per_unit = matched["payout_amount"].iloc[0]
        # payoffs are per 100 yen unit
        units = bet.amount / 100.0
        return payout_per_unit * units

    def _check_hit(self, bet: BetRecord, results_df: pd.DataFrame) -> bool:
        """Check if a bet is a winner based on actual results."""
        race_results = results_df[results_df["race_id"] == bet.race_id]
        if race_results.empty:
            return False

        combo_parts = [p.strip() for p in str(bet.combination).split("-")]

        if bet.bet_type == "単勝":
            winner = race_results[race_results["finish_position"] == 1]
            if winner.empty:
                return False
            return str(winner["horse_number"].iloc[0]) == combo_parts[0]

        elif bet.bet_type == "複勝":
            top3 = race_results[race_results["finish_position"] <= 3]
            top3_nums = set(top3["horse_number"].astype(str))
            return combo_parts[0] in top3_nums

        elif bet.bet_type == "馬連":
            top2 = race_results[race_results["finish_position"] <= 2]
            top2_nums = set(top2["horse_number"].astype(str))
            return set(combo_parts) == top2_nums

        elif bet.bet_type == "ワイド":
            top3 = race_results[race_results["finish_position"] <= 3]
            top3_nums = set(top3["horse_number"].astype(str))
            return set(combo_parts).issubset(top3_nums)

        elif bet.bet_type == "馬単":
            top2 = race_results[
                race_results["finish_position"].isin([1, 2])
            ].sort_values("finish_position")
            if len(top2) < 2:
                return False
            return (
                str(top2.iloc[0]["horse_number"]) == combo_parts[0]
                and str(top2.iloc[1]["horse_number"]) == combo_parts[1]
            )

        elif bet.bet_type == "三連複":
            top3 = race_results[race_results["finish_position"] <= 3]
            top3_nums = set(top3["horse_number"].astype(str))
            return set(combo_parts) == top3_nums

        elif bet.bet_type == "三連単":
            top3 = race_results[
                race_results["finish_position"].isin([1, 2, 3])
            ].sort_values("finish_position")
            if len(top3) < 3:
                return False
            return (
                str(top3.iloc[0]["horse_number"]) == combo_parts[0]
                and str(top3.iloc[1]["horse_number"]) == combo_parts[1]
                and str(top3.iloc[2]["horse_number"]) == combo_parts[2]
            )

        return False
