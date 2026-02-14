"""推論・勝率予測"""

import logging
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from database.repository import Repository
from features.builder import FeatureBuilder
from model.trainer import LightGBMTrainer

logger = logging.getLogger(__name__)


class Predictor:
    """学習済みモデルを用いた推論"""

    def __init__(
        self,
        model_path: str | Path | None = None,
        trainer: LightGBMTrainer | None = None,
        repo: Repository | None = None,
    ):
        self.repo = repo or Repository()
        self.feature_builder = FeatureBuilder(repo=self.repo)

        if trainer is not None:
            self.trainer = trainer
        elif model_path is not None:
            self.trainer = LightGBMTrainer.load(model_path)
        else:
            # アクティブモデルをDBから検索
            model_info = self.repo.get_active_model()
            if model_info and Path(model_info.model_path).exists():
                self.trainer = LightGBMTrainer.load(model_info.model_path)
            else:
                raise ValueError("No model available. Train a model first.")

    def predict_race(
        self,
        race_id: str,
        entries: list[dict] | pd.DataFrame | None = None,
        race_info: dict | None = None,
    ) -> pd.DataFrame:
        """1レースの全馬の勝率を予測する

        Returns:
            DataFrame: horse_number, horse_name, raw_prob, calibrated_prob, rank
        """
        if self.trainer.model is None:
            raise RuntimeError("Model not loaded")

        # レース情報取得
        if race_info is None:
            race = self.repo.get_race(race_id)
            if race is None:
                raise ValueError(f"Race not found: {race_id}")
            race_info = {
                "race_date": race.race_date,
                "distance": race.distance,
                "surface": race.surface,
                "venue_code": race.venue_code,
                "track_condition": race.track_condition,
                "race_class_code": race.race_class_code,
                "num_runners": race.num_runners,
                "weight_rule": race.weight_rule,
            }

        # 出走馬情報
        if entries is None:
            results = self.repo.get_race_results(race_id)
            entries_list = [
                {
                    "horse_id": r.horse_id,
                    "horse_name": r.horse_name,
                    "horse_number": r.horse_number,
                    "post_position": r.post_position,
                    "jockey_id": r.jockey_id,
                    "trainer_id": r.trainer_id,
                    "age": r.age,
                    "horse_weight": r.horse_weight,
                    "weight_carried": r.weight_carried,
                    "odds": r.odds,
                    "popularity": r.popularity,
                }
                for r in results
            ]
        elif isinstance(entries, pd.DataFrame):
            entries_list = entries.to_dict("records")
        else:
            entries_list = entries

        if not entries_list:
            return pd.DataFrame()

        # フィールドオッズ
        field_odds = [
            e.get("odds") for e in entries_list
            if e.get("odds") is not None and e.get("odds", 0) > 0
        ]

        # 各馬の特徴量構築 → 予測
        predictions = []
        feature_matrix = []
        rd = race_info["race_date"]
        if isinstance(rd, str):
            rd = date.fromisoformat(rd)

        for entry in entries_list:
            try:
                feats = self.feature_builder.build_for_entry(
                    race_id=race_id,
                    horse_id=entry.get("horse_id", ""),
                    horse_number=int(entry.get("horse_number", 0)),
                    post_position=int(entry.get("post_position", 0)),
                    race_date=rd,
                    race_distance=int(race_info.get("distance", 0)),
                    race_surface=str(race_info.get("surface", "")),
                    race_venue=str(race_info.get("venue_code", "")),
                    race_condition=str(race_info.get("track_condition", "")),
                    race_class_code=int(race_info.get("race_class_code", 0)),
                    num_runners=int(race_info.get("num_runners", len(entries_list))),
                    weight_carried=float(entry.get("weight_carried", 0) or 0),
                    weight_rule=str(race_info.get("weight_rule", "")),
                    jockey_id=str(entry.get("jockey_id", "")),
                    trainer_id=str(entry.get("trainer_id", "")),
                    horse_age=int(entry.get("age", 0) or 0),
                    horse_weight=int(entry["horse_weight"]) if entry.get("horse_weight") else None,
                    win_odds=float(entry["odds"]) if entry.get("odds") else None,
                    popularity=int(entry["popularity"]) if entry.get("popularity") else None,
                    field_odds=field_odds,
                    use_cache=False,
                )

                # 特徴量順序をモデルに合わせる
                feat_vector = [
                    feats.get(fn, 0.0) for fn in self.trainer.feature_names
                ]
                feature_matrix.append(feat_vector)
                predictions.append(
                    {
                        "horse_number": entry.get("horse_number", 0),
                        "horse_name": entry.get("horse_name", ""),
                        "horse_id": entry.get("horse_id", ""),
                    }
                )
            except Exception as e:
                logger.warning(
                    "Prediction failed for %s: %s",
                    entry.get("horse_name", "?"),
                    e,
                )

        if not feature_matrix:
            return pd.DataFrame()

        X = np.array(feature_matrix, dtype=np.float32)
        X = np.nan_to_num(X, nan=0.0, posinf=1e6, neginf=-1e6)

        raw_probs = self.trainer.model.predict_proba(X)[:, 1]

        # レース内で確率を正規化(合計≈1.0)
        total_prob = raw_probs.sum()
        if total_prob > 0:
            calibrated = raw_probs / total_prob
        else:
            calibrated = np.ones(len(raw_probs)) / len(raw_probs)

        for i, pred in enumerate(predictions):
            pred["raw_prob"] = float(raw_probs[i])
            pred["calibrated_prob"] = float(calibrated[i])

        result_df = pd.DataFrame(predictions)
        result_df = result_df.sort_values("calibrated_prob", ascending=False)
        result_df["rank"] = range(1, len(result_df) + 1)

        return result_df.reset_index(drop=True)

    def predict_win5_races(
        self, race_ids: list[str]
    ) -> dict[str, pd.DataFrame]:
        """Win5対象5レース全ての予測を行う"""
        results = {}
        for i, race_id in enumerate(race_ids, 1):
            logger.info("Predicting Race %d: %s", i, race_id)
            try:
                pred = self.predict_race(race_id)
                results[race_id] = pred
            except Exception as e:
                logger.error("Prediction failed for %s: %s", race_id, e)
                results[race_id] = pd.DataFrame()
        return results
