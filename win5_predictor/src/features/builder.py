"""特徴量構築オーケストレータ

全特徴量モジュールを統合し、レース単位・馬単位で特徴量ベクトルを構築する。
学習データの一括生成と、予測時の単体生成の両方をサポート。
"""

import logging
from datetime import date

import numpy as np
import pandas as pd

from database.models import Horse
from database.repository import Repository
from features.horse_features import build_horse_features
from features.interaction_features import build_interaction_features
from features.jockey_features import (
    build_jockey_features,
    build_trainer_features,
    get_jockey_horse_combo_stats,
    get_trainer_jockey_combo_stats,
)
from features.odds_features import build_odds_features
from features.pedigree_features import build_pedigree_features
from features.race_features import build_field_strength_features, build_race_features

logger = logging.getLogger(__name__)


class FeatureBuilder:
    """特徴量を一括構築するオーケストレータ"""

    def __init__(self, repo: Repository | None = None):
        self.repo = repo or Repository()

    def build_for_entry(
        self,
        race_id: str,
        horse_id: str,
        horse_number: int,
        post_position: int,
        race_date: date,
        race_distance: int,
        race_surface: str,
        race_venue: str,
        race_condition: str,
        race_class_code: int,
        num_runners: int,
        weight_carried: float,
        weight_rule: str,
        jockey_id: str,
        trainer_id: str,
        horse_age: int,
        horse_weight: int | None,
        win_odds: float | None = None,
        popularity: int | None = None,
        field_odds: list[float] | None = None,
        use_cache: bool = True,
    ) -> dict[str, float]:
        """1頭分の特徴量を構築する"""

        # キャッシュ確認
        if use_cache:
            cached = self.repo.get_cached_features(race_id, horse_id)
            if cached is not None:
                return cached

        # 馬の過去成績を取得
        horse_history = self.repo.get_horse_history(
            horse_id, before_date=race_date, limit=10
        )

        # 馬情報(血統)を取得
        horse_info = self.repo.get_horse(horse_id)
        sire_id = horse_info.sire_id if horse_info else ""
        damsire_id = horse_info.damsire_id if horse_info else ""

        # ① 馬の特徴量
        horse_feats = build_horse_features(
            horse_id=horse_id,
            race_date=race_date,
            race_distance=race_distance,
            race_surface=race_surface,
            race_venue=race_venue,
            race_condition=race_condition,
            horse_history=horse_history,
            horse_weight=horse_weight,
            horse_age=horse_age,
        )

        # ② 騎手の特徴量
        j_stats = self.repo.get_jockey_stats(jockey_id, before_date=race_date)
        j_venue = self.repo.get_jockey_stats(
            jockey_id, before_date=race_date, venue_code=race_venue
        )
        j_surface = self.repo.get_jockey_stats(
            jockey_id, before_date=race_date, surface=race_surface
        )
        j_combo = get_jockey_horse_combo_stats(
            jockey_id, horse_id, race_date, self.repo
        )
        jockey_feats = build_jockey_features(j_stats, j_venue, j_surface, j_combo)

        # ③ 調教師の特徴量
        t_stats = self.repo.get_trainer_stats(trainer_id, before_date=race_date)
        tj_combo = get_trainer_jockey_combo_stats(
            trainer_id, jockey_id, race_date, self.repo
        )
        trainer_feats = build_trainer_features(t_stats, tj_combo)

        # ④ レース特徴量
        race_feats = build_race_features(
            race_distance=race_distance,
            race_surface=race_surface,
            race_condition=race_condition,
            race_class_code=race_class_code,
            num_runners=num_runners,
            post_position=post_position,
            horse_number=horse_number,
            weight_carried=weight_carried,
            weight_rule=weight_rule,
        )

        # ⑤ オッズ特徴量
        odds_feats = build_odds_features(
            win_odds=win_odds,
            num_runners=num_runners,
            popularity=popularity,
            field_odds=field_odds,
        )

        # ⑥ 血統特徴量
        pedigree_feats = build_pedigree_features(
            sire_id=sire_id,
            damsire_id=damsire_id,
            race_surface=race_surface,
            race_distance=race_distance,
            repo=self.repo,
            before_date=race_date,
        )

        # ⑦ 交互作用特徴量
        interaction_feats = build_interaction_features(
            horse_features=horse_feats,
            jockey_features=jockey_feats,
            race_features=race_feats,
            odds_features=odds_feats,
        )
        # rest_x_trainerを調教師成績で補完
        interaction_feats["rest_x_trainer"] = (
            (horse_feats.get("days_since_last", 0.0) / 90.0)
            * trainer_feats.get("t_win_rate", 0.0)
            if horse_feats.get("days_since_last", 0.0) > 30
            else 0.0
        )

        # 全特徴量を統合
        features: dict[str, float] = {}
        features.update(horse_feats)
        features.update(jockey_feats)
        features.update(trainer_feats)
        features.update(race_feats)
        features.update(odds_feats)
        features.update(pedigree_feats)
        features.update(interaction_feats)

        # キャッシュ保存
        if use_cache:
            self.repo.cache_features(race_id, horse_id, features)

        return features

    def build_training_data(
        self,
        start: date,
        end: date,
        include_odds: bool = True,
    ) -> pd.DataFrame:
        """学習用データセットを構築する

        Returns:
            DataFrame with columns: 全特徴量 + target(1着=1, else=0) + メタ情報
        """
        logger.info("Building training data: %s to %s", start, end)

        results_df = self.repo.get_results_in_range(start, end)
        if results_df.empty:
            logger.warning("No results found in range")
            return pd.DataFrame()

        rows = []
        grouped = results_df.groupby("race_id")
        total_races = len(grouped)
        processed = 0

        for race_id, group in grouped:
            race_date_str = group.iloc[0].get("race_date", "")
            try:
                rd = date.fromisoformat(str(race_date_str))
            except (ValueError, TypeError):
                continue

            race_distance = int(group.iloc[0].get("distance", 0) or 0)
            race_surface = str(group.iloc[0].get("surface", ""))
            race_venue = str(group.iloc[0].get("venue_code", ""))
            race_condition = str(group.iloc[0].get("track_condition", ""))
            race_class_code = int(group.iloc[0].get("race_class_code", 0) or 0)
            num_runners = int(group.iloc[0].get("num_runners", len(group)) or len(group))
            weight_rule = str(group.iloc[0].get("weight_rule", ""))

            # フィールドオッズ
            field_odds = group["odds"].dropna().tolist() if "odds" in group.columns else []

            for _, row in group.iterrows():
                horse_id = str(row.get("horse_id", ""))
                finish_pos = row.get("finish_position")
                if pd.isna(finish_pos) or not horse_id:
                    continue

                try:
                    feats = self.build_for_entry(
                        race_id=str(race_id),
                        horse_id=horse_id,
                        horse_number=int(row.get("horse_number", 0) or 0),
                        post_position=int(row.get("post_position", 0) or 0),
                        race_date=rd,
                        race_distance=race_distance,
                        race_surface=race_surface,
                        race_venue=race_venue,
                        race_condition=race_condition,
                        race_class_code=race_class_code,
                        num_runners=num_runners,
                        weight_carried=float(row.get("weight_carried", 0) or 0),
                        weight_rule=weight_rule,
                        jockey_id=str(row.get("jockey_id", "")),
                        trainer_id=str(row.get("trainer_id", "")),
                        horse_age=int(row.get("age", 0) or 0),
                        horse_weight=int(row["horse_weight"]) if pd.notna(row.get("horse_weight")) else None,
                        win_odds=float(row["odds"]) if include_odds and pd.notna(row.get("odds")) else None,
                        popularity=int(row["popularity"]) if pd.notna(row.get("popularity")) else None,
                        field_odds=field_odds if include_odds else None,
                        use_cache=True,
                    )
                except Exception as e:
                    logger.debug("Feature build failed: %s/%s: %s", race_id, horse_id, e)
                    continue

                feats["_race_id"] = str(race_id)
                feats["_horse_id"] = horse_id
                feats["_race_date"] = str(rd)
                feats["_finish_position"] = int(finish_pos)
                feats["target"] = 1.0 if int(finish_pos) == 1 else 0.0
                rows.append(feats)

            processed += 1
            if processed % 100 == 0:
                logger.info("Processed %d/%d races", processed, total_races)

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        logger.info(
            "Training data: %d samples, %d features, positive rate=%.3f",
            len(df),
            len([c for c in df.columns if not c.startswith("_") and c != "target"]),
            df["target"].mean(),
        )
        return df

    def get_feature_names(self) -> list[str]:
        """特徴量名の一覧を返す(メタカラム・target除外)"""
        from features.horse_features import _empty_horse_features

        sample_keys = list(_empty_horse_features().keys())
        jockey_keys = [
            "j_win_rate", "j_top3_rate", "j_runs",
            "j_venue_win_rate", "j_venue_top3_rate", "j_venue_runs",
            "j_surface_win_rate", "j_surface_runs",
            "j_combo_win_rate", "j_combo_runs",
        ]
        trainer_keys = [
            "t_win_rate", "t_top3_rate", "t_runs",
            "tj_combo_win_rate", "tj_combo_runs",
        ]
        race_keys = [
            "distance", "distance_cat", "is_turf", "is_dirt",
            "condition_code", "is_heavy_track", "class_code",
            "num_runners", "field_size_cat",
            "post_position", "horse_number", "post_ratio",
            "is_inner_post", "is_outer_post",
            "weight_carried", "is_handicap",
        ]
        odds_keys = [
            "win_odds", "log_odds", "implied_prob",
            "popularity", "popularity_ratio", "odds_vs_favorite",
        ]
        pedigree_keys = [
            "sire_win_rate", "sire_top3_rate", "sire_runs",
            "sire_surface_win_rate", "sire_dist_win_rate",
            "damsire_win_rate", "damsire_top3_rate", "damsire_runs",
        ]
        interaction_keys = [
            "horse_x_jockey_wr", "aptitude_score", "speed_x_class",
            "edge_signal", "rest_x_trainer", "post_x_field",
        ]
        return (
            sample_keys + jockey_keys + trainer_keys + race_keys
            + odds_keys + pedigree_keys + interaction_keys
        )
