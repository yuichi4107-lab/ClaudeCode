"""過去データによるバックテスト

指定期間のWin5を過去データでシミュレーションし、モデルの有効性を検証する。
"""

import logging
from datetime import date, timedelta

import numpy as np
import pandas as pd

from database.repository import Repository
from features.builder import FeatureBuilder
from model.predictor import Predictor
from optimizer.budget_optimizer import BudgetOptimizer
from optimizer.expected_value import ExpectedValueCalculator
from optimizer.win5_combiner import Win5Combiner

logger = logging.getLogger(__name__)


class Backtester:
    """Win5バックテストシミュレーター"""

    def __init__(
        self,
        predictor: Predictor,
        repo: Repository | None = None,
        budget: int = 10000,
    ):
        self.predictor = predictor
        self.repo = repo or Repository()
        self.budget = budget

    def run(self, start: date, end: date) -> pd.DataFrame:
        """期間内のWin5をバックテストする"""
        logger.info("Backtest: %s to %s, budget=¥%d", start, end, self.budget)

        events = self.repo.get_win5_events_in_range(start, end)
        if not events:
            logger.warning("No Win5 events found in range")
            return pd.DataFrame()

        results = []
        for event in events:
            result = self._test_event(event)
            if result:
                results.append(result)

        if not results:
            return pd.DataFrame()

        df = pd.DataFrame(results)
        self._log_summary(df)
        return df

    def _test_event(self, event) -> dict | None:
        """1回のWin5イベントをシミュレートする"""
        race_ids = [
            event.race1_id,
            event.race2_id,
            event.race3_id,
            event.race4_id,
            event.race5_id,
        ]
        race_ids = [r for r in race_ids if r]

        if len(race_ids) < 5:
            return None

        try:
            # 5レースの予測
            predictions = self.predictor.predict_win5_races(race_ids)
            valid_preds = {k: v for k, v in predictions.items() if not v.empty}
            if len(valid_preds) < 5:
                return None

            # 最適買い目の決定
            combiner = Win5Combiner(valid_preds)
            optimizer = BudgetOptimizer(combiner, budget=self.budget)
            ticket = optimizer.optimize(max_per_race=6)

            if ticket is None:
                return None

            # 実際の結果との照合
            is_hit = self._check_hit(ticket, race_ids)
            actual_payout = float(event.payout or 0)

            return {
                "event_date": str(event.event_date),
                "event_id": event.event_id,
                "num_combinations": ticket.num_combinations,
                "total_cost": ticket.total_cost,
                "hit_probability": ticket.total_hit_probability,
                "is_hit": is_hit,
                "actual_payout": actual_payout if is_hit else 0.0,
                "profit": (actual_payout - ticket.total_cost) if is_hit else -ticket.total_cost,
            }

        except Exception as e:
            logger.error("Backtest failed for %s: %s", event.event_id, e)
            return None

    def _check_hit(self, ticket, race_ids: list[str]) -> bool:
        """購入した買い目が的中したかチェックする"""
        for sel in ticket.selections:
            # 実際の1着馬を取得
            results = self.repo.get_race_results(sel.race_id)
            winner = None
            for r in results:
                if r.finish_position == 1:
                    winner = r.horse_number
                    break

            if winner is None or winner not in sel.horse_numbers:
                return False

        return True

    def _log_summary(self, df: pd.DataFrame):
        """バックテスト結果のサマリーをログ出力"""
        total_events = len(df)
        total_cost = df["total_cost"].sum()
        total_payout = df["actual_payout"].sum()
        hits = df["is_hit"].sum()
        hit_rate = hits / total_events if total_events > 0 else 0
        roi = (total_payout / total_cost - 1.0) * 100 if total_cost > 0 else 0

        logger.info("=" * 50)
        logger.info("Backtest Results:")
        logger.info("  Events: %d", total_events)
        logger.info("  Hits: %d (%.1f%%)", hits, hit_rate * 100)
        logger.info("  Total Cost: ¥%,.0f", total_cost)
        logger.info("  Total Payout: ¥%,.0f", total_payout)
        logger.info("  Profit: ¥%,.0f", total_payout - total_cost)
        logger.info("  ROI: %.1f%%", roi)
        logger.info("=" * 50)
