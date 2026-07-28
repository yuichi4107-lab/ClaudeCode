"""レースフィルタリングモジュール"""

import numpy as np
import pandas as pd


class RaceFilter:
    """Filter and score races to determine which ones to bet on."""

    def __init__(self, config: dict):
        """Initialize from strategies.yaml -> race_filter section."""
        rf = config.get("race_filter", {})
        self.min_horse_count = rf.get("min_horse_count", 8)
        self.allowed_race_types = rf.get("allowed_race_types", ["芝", "ダート"])
        self.min_data_coverage = rf.get("min_data_coverage", 0.80)
        self.weights = rf.get("score_weights", {})
        self.target_purchase_rate = rf.get("target_purchase_rate", 0.30)

    def calculate_race_score(
        self, race_df: pd.DataFrame, probas: np.ndarray
    ) -> float:
        """Score a race for betting suitability.

        Score = 0.30 * model_confidence + 0.25 * value_opportunity
              + 0.20 * data_quality + 0.15 * field_size_score
              + 0.10 * historical_accuracy

        Returns:
            Score between 0.0 and 1.0.
        """
        w = self.weights
        w_conf = w.get("model_confidence", 0.30)
        w_value = w.get("value_opportunity", 0.25)
        w_quality = w.get("data_quality", 0.20)
        w_field = w.get("field_size", 0.15)
        w_hist = w.get("historical_accuracy", 0.10)

        # Model confidence: how concentrated top predictions are
        sorted_probs = np.sort(probas)[::-1]
        top3_sum = sorted_probs[:3].sum() if len(sorted_probs) >= 3 else sorted_probs.sum()
        model_confidence = min(1.0, top3_sum)

        # Value opportunity: fraction of horses with EV > 1.0
        # Estimate odds from probabilities (implied odds)
        if "odds" in race_df.columns:
            odds = race_df["odds"].values
            evs = probas * odds
            value_opportunity = (evs > 1.0).sum() / len(probas)
        else:
            value_opportunity = 0.5  # default when odds unavailable

        # Data quality: 1 - fraction of missing features
        total_cells = race_df.shape[0] * race_df.shape[1]
        missing_cells = race_df.isnull().sum().sum()
        data_quality = 1.0 - (missing_cells / total_cells) if total_cells > 0 else 0.0

        # Field size score: peaks at 12-16 horses
        n = len(race_df)
        if 12 <= n <= 16:
            field_size_score = 1.0
        elif 10 <= n < 12 or 16 < n <= 18:
            field_size_score = 0.8
        elif 8 <= n < 10:
            field_size_score = 0.6
        else:
            field_size_score = 0.4

        # Historical accuracy: placeholder
        historical_accuracy = 1.0

        score = (
            w_conf * model_confidence
            + w_value * value_opportunity
            + w_quality * data_quality
            + w_field * field_size_score
            + w_hist * historical_accuracy
        )
        return float(np.clip(score, 0.0, 1.0))

    def passes_basic_filter(self, race_df: pd.DataFrame) -> bool:
        """Check minimum horse count and allowed race types."""
        if len(race_df) < self.min_horse_count:
            return False

        if "race_type" in race_df.columns:
            race_type = race_df["race_type"].iloc[0]
            if race_type not in self.allowed_race_types:
                return False

        # Data coverage check
        total_cells = race_df.shape[0] * race_df.shape[1]
        if total_cells > 0:
            coverage = 1.0 - (race_df.isnull().sum().sum() / total_cells)
            if coverage < self.min_data_coverage:
                return False

        return True

    def select_races(
        self, all_race_scores: dict, target_rate: float = None
    ) -> list:
        """Select top N% of races by score to hit target purchase rate.

        Args:
            all_race_scores: {race_id: score} mapping.
            target_rate: Fraction of races to select (default from config).

        Returns:
            List of selected race_ids.
        """
        if target_rate is None:
            target_rate = self.target_purchase_rate

        if not all_race_scores:
            return []

        sorted_races = sorted(
            all_race_scores.items(), key=lambda x: x[1], reverse=True
        )
        n_select = max(1, int(len(sorted_races) * target_rate))
        return [race_id for race_id, _score in sorted_races[:n_select]]
