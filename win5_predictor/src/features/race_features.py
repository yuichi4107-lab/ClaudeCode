"""レース特徴量 (~10個)

場の強さ, ペース予測, 脚質適合度, 枠順バイアス 等
"""

import numpy as np
import pandas as pd
from datetime import date

from config.venues import RACE_CLASS, distance_category


def build_race_features(
    race_distance: int,
    race_surface: str,
    race_condition: str,
    race_class_code: int,
    num_runners: int,
    post_position: int,
    horse_number: int,
    weight_carried: float,
    weight_rule: str = "",
) -> dict[str, float]:
    """レース条件に関する特徴量を構築する"""
    f: dict[str, float] = {}

    # 距離
    f["distance"] = float(race_distance)
    f["distance_cat"] = _encode_distance_cat(race_distance)

    # 馬場
    f["is_turf"] = 1.0 if race_surface == "turf" else 0.0
    f["is_dirt"] = 1.0 if race_surface == "dirt" else 0.0

    # 馬場状態
    f["condition_code"] = _encode_condition(race_condition)
    f["is_heavy_track"] = 1.0 if race_condition in ("heavy", "bad") else 0.0

    # クラス
    f["class_code"] = float(race_class_code)

    # 出走頭数
    f["num_runners"] = float(num_runners)
    f["field_size_cat"] = _encode_field_size(num_runners)

    # 枠順
    f["post_position"] = float(post_position)
    f["horse_number"] = float(horse_number)

    # 枠順バイアス(内枠=1, 外枠=高い数字)
    if num_runners > 0:
        f["post_ratio"] = float(horse_number) / float(num_runners)
    else:
        f["post_ratio"] = 0.5

    f["is_inner_post"] = 1.0 if horse_number <= 4 else 0.0
    f["is_outer_post"] = 1.0 if horse_number >= 13 else 0.0

    # 斤量
    f["weight_carried"] = weight_carried

    # 重量規定
    f["is_handicap"] = 1.0 if weight_rule == "ハンデ" else 0.0

    return f


def build_field_strength_features(
    race_id: str,
    entries: pd.DataFrame,
) -> dict[str, float]:
    """場の強さの特徴量を構築する"""
    f: dict[str, float] = {}

    if entries.empty:
        f["field_avg_odds"] = 10.0
        f["field_min_odds"] = 1.5
        f["favorite_odds"] = 1.5
        return f

    if "odds" in entries.columns:
        odds_vals = entries["odds"].dropna()
        f["field_avg_odds"] = float(odds_vals.mean()) if len(odds_vals) > 0 else 10.0
        f["field_min_odds"] = float(odds_vals.min()) if len(odds_vals) > 0 else 1.5
        f["favorite_odds"] = f["field_min_odds"]
    else:
        f["field_avg_odds"] = 10.0
        f["field_min_odds"] = 1.5
        f["favorite_odds"] = 1.5

    return f


def _encode_distance_cat(distance: int) -> float:
    """距離カテゴリを数値化"""
    cat = distance_category(distance)
    mapping = {"sprint": 1.0, "mile": 2.0, "intermediate": 3.0, "long": 4.0, "extended": 5.0}
    return mapping.get(cat, 3.0)


def _encode_condition(condition: str) -> float:
    """馬場状態を数値化"""
    mapping = {"good": 0.0, "slightly_heavy": 1.0, "heavy": 2.0, "bad": 3.0}
    return mapping.get(condition, 0.0)


def _encode_field_size(n: int) -> float:
    """頭数をカテゴリ化"""
    if n <= 8:
        return 1.0  # 少頭数
    elif n <= 13:
        return 2.0  # 中頭数
    else:
        return 3.0  # 多頭数
