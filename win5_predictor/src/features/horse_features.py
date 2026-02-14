"""馬の特徴量 (~30個)

- 近走成績 (勝率, 複勝率, 平均着順, 休養日数, 連勝数 等)
- スピード指数 (上がり3F平均, 距離ベストタイム 等)
- 適性 (距離別勝率, 馬場別勝率, 競馬場別勝率 等)
- 状態 (馬体重, 増減, 年齢 等)
"""

import numpy as np
import pandas as pd
from datetime import date

from config.settings import RECENT_RUNS, MAX_RECENT_RUNS
from config.venues import distance_category


def build_horse_features(
    horse_id: str,
    race_date: date,
    race_distance: int,
    race_surface: str,
    race_venue: str,
    race_condition: str,
    horse_history: pd.DataFrame,
    horse_weight: int | None = None,
    horse_age: int = 0,
) -> dict[str, float]:
    """馬の特徴量を構築する"""
    features: dict[str, float] = {}

    if horse_history.empty:
        return _empty_horse_features()

    # データ型変換
    hist = horse_history.copy()
    for col in ["finish_position", "odds", "last_3f", "finish_time", "horse_weight"]:
        if col in hist.columns:
            hist[col] = pd.to_numeric(hist[col], errors="coerce")

    # ──────────────────────────────────
    # 近走成績 (~15)
    # ──────────────────────────────────
    recent = hist.head(RECENT_RUNS)
    all_runs = hist.head(MAX_RECENT_RUNS)

    valid_positions = recent["finish_position"].dropna()
    all_valid = all_runs["finish_position"].dropna()

    n_recent = len(valid_positions)
    features["recent_runs"] = float(n_recent)
    features["win_rate_5"] = (
        float((valid_positions == 1).mean()) if n_recent > 0 else 0.0
    )
    features["top3_rate_5"] = (
        float((valid_positions <= 3).mean()) if n_recent > 0 else 0.0
    )
    features["avg_position_5"] = (
        float(valid_positions.mean()) if n_recent > 0 else 10.0
    )
    features["best_position_5"] = (
        float(valid_positions.min()) if n_recent > 0 else 18.0
    )

    n_all = len(all_valid)
    features["win_rate_10"] = (
        float((all_valid == 1).mean()) if n_all > 0 else 0.0
    )
    features["top3_rate_10"] = (
        float((all_valid <= 3).mean()) if n_all > 0 else 0.0
    )
    features["avg_position_10"] = (
        float(all_valid.mean()) if n_all > 0 else 10.0
    )

    # 前走着順
    features["last_finish"] = (
        float(valid_positions.iloc[0]) if n_recent > 0 else 10.0
    )
    features["last2_finish"] = (
        float(valid_positions.iloc[1]) if n_recent > 1 else 10.0
    )

    # 連勝数
    streak = 0
    for pos in valid_positions:
        if pos == 1:
            streak += 1
        else:
            break
    features["win_streak"] = float(streak)

    # 連続複勝圏
    place_streak = 0
    for pos in valid_positions:
        if pos <= 3:
            place_streak += 1
        else:
            break
    features["place_streak"] = float(place_streak)

    # 休養日数
    if "race_date" in hist.columns and len(hist) > 0:
        last_race_date = pd.to_datetime(hist.iloc[0]["race_date"]).date()
        features["days_since_last"] = float((race_date - last_race_date).days)
    else:
        features["days_since_last"] = 180.0

    features["is_long_rest"] = 1.0 if features["days_since_last"] > 90 else 0.0

    # ──────────────────────────────────
    # スピード (~8)
    # ──────────────────────────────────
    if "last_3f" in recent.columns:
        l3f = recent["last_3f"].dropna()
        features["avg_last_3f"] = float(l3f.mean()) if len(l3f) > 0 else 36.0
        features["best_last_3f"] = float(l3f.min()) if len(l3f) > 0 else 36.0
        features["last_3f_rank_ratio"] = float(
            (l3f < l3f.median()).mean()
        ) if len(l3f) > 1 else 0.5
    else:
        features["avg_last_3f"] = 36.0
        features["best_last_3f"] = 36.0
        features["last_3f_rank_ratio"] = 0.5

    if "finish_time" in recent.columns:
        ft = recent["finish_time"].dropna()
        features["avg_time"] = float(ft.mean()) if len(ft) > 0 else 120.0
        features["best_time"] = float(ft.min()) if len(ft) > 0 else 120.0
    else:
        features["avg_time"] = 120.0
        features["best_time"] = 120.0

    # スピード指数(簡易版): 基準タイムとの差を標準化
    if "finish_time" in recent.columns and "distance" in recent.columns:
        speed_indices = []
        for _, row in recent.iterrows():
            if pd.notna(row.get("finish_time")) and pd.notna(row.get("distance")):
                dist = float(row["distance"])
                time_val = float(row["finish_time"])
                if dist > 0 and time_val > 0:
                    # 1m当たりの秒数を指数化
                    per_m = time_val / dist
                    idx = (0.06 - per_m) * 1000  # 高いほど速い
                    speed_indices.append(idx)
        features["speed_index"] = (
            float(np.mean(speed_indices)) if speed_indices else 0.0
        )
        features["best_speed_index"] = (
            float(max(speed_indices)) if speed_indices else 0.0
        )
    else:
        features["speed_index"] = 0.0
        features["best_speed_index"] = 0.0

    # ──────────────────────────────────
    # 適性 (~10)
    # ──────────────────────────────────
    dist_cat = distance_category(race_distance)

    # 距離別
    if "distance" in all_runs.columns:
        dist_cats = all_runs["distance"].apply(
            lambda x: distance_category(int(x)) if pd.notna(x) else ""
        )
        same_dist = all_runs[dist_cats == dist_cat]
        same_positions = same_dist["finish_position"].dropna() if not same_dist.empty else pd.Series(dtype=float)
        features["dist_win_rate"] = (
            float((same_positions == 1).mean()) if len(same_positions) > 0 else 0.0
        )
        features["dist_top3_rate"] = (
            float((same_positions <= 3).mean()) if len(same_positions) > 0 else 0.0
        )
        features["dist_runs"] = float(len(same_positions))
    else:
        features["dist_win_rate"] = 0.0
        features["dist_top3_rate"] = 0.0
        features["dist_runs"] = 0.0

    # 馬場別
    if "surface" in all_runs.columns:
        same_surface = all_runs[all_runs["surface"] == race_surface]
        sf_pos = same_surface["finish_position"].dropna() if not same_surface.empty else pd.Series(dtype=float)
        features["surface_win_rate"] = (
            float((sf_pos == 1).mean()) if len(sf_pos) > 0 else 0.0
        )
        features["surface_top3_rate"] = (
            float((sf_pos <= 3).mean()) if len(sf_pos) > 0 else 0.0
        )
    else:
        features["surface_win_rate"] = 0.0
        features["surface_top3_rate"] = 0.0

    # 競馬場別
    if "venue_code" in all_runs.columns:
        same_venue = all_runs[all_runs["venue_code"] == race_venue]
        vn_pos = same_venue["finish_position"].dropna() if not same_venue.empty else pd.Series(dtype=float)
        features["venue_win_rate"] = (
            float((vn_pos == 1).mean()) if len(vn_pos) > 0 else 0.0
        )
        features["venue_runs"] = float(len(vn_pos))
    else:
        features["venue_win_rate"] = 0.0
        features["venue_runs"] = 0.0

    # 馬場状態別
    if "track_condition" in all_runs.columns:
        same_cond = all_runs[all_runs["track_condition"] == race_condition]
        cd_pos = same_cond["finish_position"].dropna() if not same_cond.empty else pd.Series(dtype=float)
        features["condition_win_rate"] = (
            float((cd_pos == 1).mean()) if len(cd_pos) > 0 else 0.0
        )
    else:
        features["condition_win_rate"] = 0.0

    # ──────────────────────────────────
    # 状態 (~5)
    # ──────────────────────────────────
    features["age"] = float(horse_age)
    features["horse_weight"] = float(horse_weight) if horse_weight else 470.0

    # 前走からの体重変化
    if horse_weight and "horse_weight" in hist.columns:
        prev_weights = hist["horse_weight"].dropna()
        if len(prev_weights) > 0:
            avg_weight = float(prev_weights.mean())
            features["weight_deviation"] = float(horse_weight) - avg_weight
        else:
            features["weight_deviation"] = 0.0
    else:
        features["weight_deviation"] = 0.0

    # クラス昇降
    if "race_class_code" in hist.columns:
        prev_class = hist["race_class_code"].dropna()
        if len(prev_class) > 0:
            features["class_change"] = 0.0  # 未実装時はデフォルト
        else:
            features["class_change"] = 0.0
    else:
        features["class_change"] = 0.0

    return features


def _empty_horse_features() -> dict[str, float]:
    """データなし時のデフォルト特徴量"""
    return {
        "recent_runs": 0.0,
        "win_rate_5": 0.0,
        "top3_rate_5": 0.0,
        "avg_position_5": 10.0,
        "best_position_5": 18.0,
        "win_rate_10": 0.0,
        "top3_rate_10": 0.0,
        "avg_position_10": 10.0,
        "last_finish": 10.0,
        "last2_finish": 10.0,
        "win_streak": 0.0,
        "place_streak": 0.0,
        "days_since_last": 180.0,
        "is_long_rest": 1.0,
        "avg_last_3f": 36.0,
        "best_last_3f": 36.0,
        "last_3f_rank_ratio": 0.5,
        "avg_time": 120.0,
        "best_time": 120.0,
        "speed_index": 0.0,
        "best_speed_index": 0.0,
        "dist_win_rate": 0.0,
        "dist_top3_rate": 0.0,
        "dist_runs": 0.0,
        "surface_win_rate": 0.0,
        "surface_top3_rate": 0.0,
        "venue_win_rate": 0.0,
        "venue_runs": 0.0,
        "condition_win_rate": 0.0,
        "age": 3.0,
        "horse_weight": 470.0,
        "weight_deviation": 0.0,
        "class_change": 0.0,
    }
