"""資金推移記録・追跡"""

import logging
from datetime import date

import pandas as pd

from database.repository import Repository

logger = logging.getLogger(__name__)


class BankrollTracker:
    """資金の推移を記録・追跡する"""

    def __init__(self, initial_balance: float = 100000, repo: Repository | None = None):
        self.repo = repo or Repository()
        self.balance = initial_balance

    def deposit(self, amount: float, record_date: date | None = None):
        """入金"""
        record_date = record_date or date.today()
        self.balance += amount
        self.repo.record_bankroll(
            record_date=record_date,
            balance=self.balance,
            deposit=amount,
            note="入金",
        )
        logger.info("Deposit: ¥%,.0f → Balance: ¥%,.0f", amount, self.balance)

    def withdraw(self, amount: float, record_date: date | None = None):
        """出金"""
        record_date = record_date or date.today()
        self.balance -= amount
        self.repo.record_bankroll(
            record_date=record_date,
            balance=self.balance,
            withdrawal=amount,
            note="出金",
        )
        logger.info("Withdraw: ¥%,.0f → Balance: ¥%,.0f", amount, self.balance)

    def record_bet(
        self,
        bet_amount: float,
        payout: float = 0.0,
        record_date: date | None = None,
        note: str = "",
    ):
        """ベットと配当を記録する"""
        record_date = record_date or date.today()
        self.balance = self.balance - bet_amount + payout
        self.repo.record_bankroll(
            record_date=record_date,
            balance=self.balance,
            bet_amount=bet_amount,
            payout=payout,
            note=note,
        )
        logger.info(
            "Bet: -¥%,.0f, Payout: +¥%,.0f → Balance: ¥%,.0f",
            bet_amount,
            payout,
            self.balance,
        )

    def get_history(self) -> pd.DataFrame:
        """資金推移履歴を取得する"""
        return self.repo.get_bankroll_history()

    def get_summary(self) -> dict[str, float]:
        """資金管理のサマリーを返す"""
        history = self.get_history()
        if history.empty:
            return {
                "current_balance": self.balance,
                "total_deposit": 0.0,
                "total_withdrawal": 0.0,
                "total_bet": 0.0,
                "total_payout": 0.0,
                "total_profit": 0.0,
                "roi_percent": 0.0,
            }

        total_deposit = float(history["deposit"].sum())
        total_withdrawal = float(history["withdrawal"].sum())
        total_bet = float(history["bet_amount"].sum())
        total_payout = float(history["payout"].sum())
        total_profit = total_payout - total_bet

        return {
            "current_balance": self.balance,
            "total_deposit": total_deposit,
            "total_withdrawal": total_withdrawal,
            "total_bet": total_bet,
            "total_payout": total_payout,
            "total_profit": total_profit,
            "roi_percent": (total_payout / total_bet - 1.0) * 100 if total_bet > 0 else 0.0,
        }
