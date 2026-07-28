"""統合特徴量パイプラインモジュール"""

import pandas as pd
from typing import Dict, List, Optional

from src.features.speed_index import SpeedIndexCalculator
from src.features.pace_index import PaceIndexCalculator
from src.features.horse_features import HorseFeatureCalculator
from src.features.jockey_features import JockeyFeatureCalculator
from src.features.race_features import RaceFeatureCalculator
from src.features.market_features import MarketFeatureCalculator
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class FeaturePipeline:
    """全特徴量を統合して特徴量行列を構築するパイプライン"""

    def __init__(self, db_manager):
        self.db = db_manager
        self.speed_calc = SpeedIndexCalculator(db_manager)
        self.pace_calc = PaceIndexCalculator()
        self.horse_calc = HorseFeatureCalculator(db_manager)
        self.jockey_calc = JockeyFeatureCalculator(db_manager)
        self.race_calc = RaceFeatureCalculator(db_manager)
        self.market_calc = MarketFeatureCalculator()

    def build_features_for_race(
        self, race_id: str, race_date: str
    ) -> Optional[pd.DataFrame]:
        """1レースの全出走馬の特徴量行列を構築する。

        Returns:
            DataFrame (1行=1頭) または出走馬がいない場合はNone
        """
        race = self.db.get_race(race_id)
        if race is None:
            logger.warning("Race not found: %s", race_id)
            return None

        results = self.db.get_race_results(race_id)
        if not results:
            logger.warning("No results for race: %s", race_id)
            return None

        rows = []
        speed_indices_for_field = []

        for result_row in results:
            horse_id = result_row.get("horse_id")
            jockey_id = result_row.get("jockey_id", "")
            trainer_id = result_row.get("trainer_id", "")

            if not horse_id:
                continue

            row: Dict = {
                "race_id": race_id,
                "race_date": race_date,
                "horse_id": horse_id,
                "horse_name": result_row.get("horse_name", ""),
                "finish_order": result_row.get("finish_order"),
            }

            # スピード指数特徴量
            speed_features = self.speed_calc.compute_features(horse_id, race_date)
            row.update(speed_features)

            # スピード指数をフィールド品質用に収集
            if speed_features.get("speed_index_last3") is not None:
                speed_indices_for_field.append(speed_features["speed_index_last3"])

            # ペース指数特徴量
            pace_features = self.pace_calc.compute_features(
                horse_id, race_date, db_manager=self.db
            )
            row.update(pace_features)

            # 馬固有特徴量
            horse_features = self.horse_calc.compute_features(
                horse_id, race_date,
                current_race=race,
                current_result=result_row,
            )
            row.update(horse_features)

            # 騎手特徴量
            jockey_features = self.jockey_calc.compute_features(
                jockey_id=jockey_id,
                horse_id=horse_id,
                trainer_id=trainer_id,
                before_date=race_date,
                venue_code=race.get("venue_code"),
                surface_type=race.get("race_type"),
                distance=race.get("distance"),
                weight_carry=result_row.get("weight_carry"),
            )
            row.update(jockey_features)

            # レース特徴量
            race_features = self.race_calc.compute_features(
                race, result_row, race_date
            )
            row.update(race_features)

            # 市場特徴量
            market_features = self.market_calc.compute_features(
                result_row, results
            )
            row.update(market_features)

            rows.append(row)

        if not rows:
            return None

        df = pd.DataFrame(rows)

        # field_quality: レース出走馬のスピード指数平均
        if speed_indices_for_field:
            field_quality = sum(speed_indices_for_field) / len(speed_indices_for_field)
            df["field_quality"] = field_quality
        else:
            df["field_quality"] = None

        # 欠損値処理
        df = self._handle_missing_values(df)

        return df

    def build_features_for_date_range(
        self, start_date: str, end_date: str
    ) -> pd.DataFrame:
        """日付範囲内の全レースの特徴量行列を構築する。"""
        races = self.db.get_races_by_date_range(start_date, end_date)
        logger.info(
            "Building features for %d races (%s to %s)",
            len(races), start_date, end_date,
        )

        all_dfs = []
        for i, race in enumerate(races):
            race_id = race["race_id"]
            race_date = race["race_date"]

            try:
                df = self.build_features_for_race(race_id, race_date)
                if df is not None:
                    all_dfs.append(df)
            except Exception as e:
                logger.error("Error building features for %s: %s", race_id, e)
                continue

            if (i + 1) % 100 == 0:
                logger.info("Processed %d / %d races", i + 1, len(races))

        if not all_dfs:
            logger.warning("No features built for date range %s to %s", start_date, end_date)
            return pd.DataFrame()

        result = pd.concat(all_dfs, ignore_index=True)
        logger.info("Built feature matrix: %d rows x %d columns", len(result), len(result.columns))
        return result

    @staticmethod
    def _handle_missing_values(df: pd.DataFrame) -> pd.DataFrame:
        """欠損値を処理する。数値列はmedianで、それ以外は-1で埋める。"""
        meta_cols = {"race_id", "race_date", "horse_id", "horse_name", "finish_order"}
        numeric_cols = [
            c for c in df.columns
            if c not in meta_cols and df[c].dtype in ("float64", "int64", "float32", "int32")
        ]
        for col in numeric_cols:
            if df[col].isna().any():
                median_val = df[col].median()
                if pd.isna(median_val):
                    median_val = 0.0
                df[col] = df[col].fillna(median_val)

        # 残りの数値的None列
        for col in df.columns:
            if col not in meta_cols and df[col].isna().any():
                df[col] = df[col].fillna(0.0)

        return df

    def get_feature_names(self) -> List[str]:
        """全特徴量カラム名のリストを返す。"""
        return [
            # Speed index
            "speed_index_last3", "speed_index_best3", "speed_index_std",
            # Pace index
            "pace_index_last3", "running_style",
            # Horse features
            "win_rate_all", "top3_rate_all",
            "win_rate_recent5", "top3_rate_recent5",
            "avg_finish_position",
            "final_3f_avg", "final_3f_best",
            "horse_weight", "weight_change",
            "days_since_last_race",
            "age", "sex_code",
            "career_races",
            "distance_wins", "surface_wins", "venue_wins", "condition_perf",
            "class_level",
            "corner_position_avg",
            "weight_carry_diff",
            # Jockey features
            "jockey_win_rate_1y", "jockey_top3_rate_1y",
            "jockey_venue_rate", "jockey_surface_rate", "jockey_distance_rate",
            "jockey_trainer_combo", "jockey_horse_combo",
            "jockey_avg_odds_win",
            "jockey_change_flag", "jockey_weight_range",
            # Race features
            "horse_count", "distance", "distance_category",
            "surface_type", "track_condition_code",
            "venue_code", "direction_code", "grade_code",
            "month", "is_special_race",
            "frame_number", "horse_number",
            "post_position_bias", "field_quality",
            # Market features
            "odds", "log_odds",
            "popularity", "implied_probability",
            "odds_gap_1st_2nd", "favorite_strength", "odds_concentration",
            "model_vs_market", "expected_value",
        ]
