"""オッズ・市場関連特徴量算出モジュール"""

import math
from typing import Dict, List, Optional

from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class MarketFeatureCalculator:
    """オッズ・市場に関する10特徴量を算出する"""

    def compute_features(
        self,
        result_row: Dict,
        all_results: List[Dict],
    ) -> Dict[str, Optional[float]]:
        """市場関連の10特徴量を算出する。

        result_row: 当該馬の race_results 行
        all_results: 同レース全馬の race_results リスト
        """
        features: Dict[str, Optional[float]] = {}

        odds = result_row.get("odds")
        popularity = result_row.get("popularity")

        # --- オッズ ---
        features["odds"] = float(odds) if odds is not None else None

        # --- 対数オッズ ---
        if odds is not None and odds > 0:
            features["log_odds"] = math.log(odds)
        else:
            features["log_odds"] = None

        # --- 人気 ---
        features["popularity"] = float(popularity) if popularity is not None else None

        # --- 暗黙的な勝利確率 (正規化済み) ---
        all_odds = [
            r["odds"] for r in all_results
            if r.get("odds") is not None and r["odds"] > 0
        ]
        if odds is not None and odds > 0 and all_odds:
            raw_probs = [1.0 / o for o in all_odds]
            total_prob = sum(raw_probs)
            if total_prob > 0:
                features["implied_probability"] = (1.0 / odds) / total_prob
            else:
                features["implied_probability"] = None
        else:
            features["implied_probability"] = None

        # --- 1番人気と2番人気のオッズ差 ---
        sorted_odds = sorted(all_odds) if all_odds else []
        if len(sorted_odds) >= 2:
            features["odds_gap_1st_2nd"] = sorted_odds[1] - sorted_odds[0]
        else:
            features["odds_gap_1st_2nd"] = None

        # --- 1番人気の強さ ---
        if sorted_odds:
            features["favorite_strength"] = sorted_odds[0]
        else:
            features["favorite_strength"] = None

        # --- オッズ集中度 (HHI) ---
        if all_odds:
            raw_probs = [1.0 / o for o in all_odds]
            total_prob = sum(raw_probs)
            if total_prob > 0:
                normalized = [p / total_prob for p in raw_probs]
                features["odds_concentration"] = sum(p ** 2 for p in normalized)
            else:
                features["odds_concentration"] = None
        else:
            features["odds_concentration"] = None

        # --- プレースホルダー (モデル予測後に設定) ---
        features["model_vs_market"] = None
        features["expected_value"] = None

        return features
