"""autorace_evaluator メトリクステスト用の合成データ生成器。

「真の能力」を埋め込んだレース群を生成し、指標がそれを復元できるかを
検証する(実HTMLが取得できない環境でも走る)。
"""

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

ENTRY_DEFAULTS = {
    "race_id": None, "venue": "kawaguchi", "race_date": "2026-01-01",
    "race_no": 1, "meeting_id": None, "track_status": "良走路",
    "distance": 3100, "car_no": 1, "player_no": None, "player_name": None,
    "handicap": 0, "trial_time": 3.35, "is_retrial": 0, "race_time": None,
    "last_lap_time": None, "st": 0.10, "is_flying": 0, "finish_pos": 1,
    "status": "finished",
}


def make_entries_df(rows):
    """辞書のリストから、既定値を補完した entries DataFrame を作る。"""
    filled = []
    for row in rows:
        d = dict(ENTRY_DEFAULTS)
        d.update(row)
        if d["race_id"] is None:
            d["race_id"] = f"{d['venue']}_{d['race_date']}_{d['race_no']}"
        if d["meeting_id"] is None:
            d["meeting_id"] = f"{d['venue']}_{d['race_date'][:7]}"
        if d["player_name"] is None and d["player_no"] is not None:
            d["player_name"] = f"選手{d['player_no']}"
        filled.append(d)
    return pd.DataFrame(filled)


def synthetic_league(seed=0, n_players=50, n_races=500, cars_per_race=8,
                     dash_sd=0.03, attack_sd=0.5):
    """真のダッシュ力・突っ込み力を埋め込んだレース群を生成する。

    Returns:
        entries_df, truth(DataFrame: player_no, true_dash, true_attack)
    """
    rng = np.random.default_rng(seed)
    players = np.arange(1, n_players + 1)
    true_dash = rng.normal(0, dash_sd, n_players)      # 序盤で得する per-100m 秒
    true_attack = rng.normal(0, attack_sd, n_players)  # 着順を押し上げる力
    machine = rng.normal(3.35, 0.03, n_players)        # 機材速度(試走タイムの中心)
    st_mean = rng.normal(0.10, 0.03, n_players)

    rows = []
    start = date(2026, 1, 1)
    for r in range(n_races):
        day = (start + timedelta(days=r // 12)).isoformat()
        race_no = r % 12 + 1
        idx = rng.choice(n_players, size=cars_per_race, replace=False)
        trial = machine[idx] + rng.normal(0, 0.02, cars_per_race)
        # 速い機材ほど重いハンデ(実戦と同じ相関構造を再現)
        handicap = (np.argsort(np.argsort(-trial)) // 2) * 10
        st = np.clip(st_mean[idx] + rng.normal(0, 0.03, cars_per_race), 0.01, None)

        # early_loss: ST・機材・ハンデの寄与 − 真のダッシュ力 + ノイズ
        early_loss = (
            0.30 + 1.5 * st + 0.8 * (trial - 3.35) + 0.002 * handicap
            - true_dash[idx] + rng.normal(0, 0.01, cars_per_race)
        )
        last_lap = trial + rng.normal(0, 0.01, cars_per_race)
        race_time = last_lap + early_loss

        # 着順: 実力(試走・ハンデ) − 突っ込み力 + ノイズ の順位
        perf = (
            10 * (trial - 3.35) - 0.05 * handicap
            - true_attack[idx] + rng.normal(0, 0.5, cars_per_race)
        )
        finish = np.argsort(np.argsort(perf)) + 1

        for c in range(cars_per_race):
            rows.append({
                "race_date": day, "race_no": race_no,
                "car_no": c + 1, "player_no": int(idx[c] + 1),
                "handicap": int(handicap[c]),
                "trial_time": round(float(trial[c]), 2),
                "race_time": round(float(race_time[c]), 3),
                "last_lap_time": round(float(last_lap[c]), 3),
                "st": round(float(st[c]), 2),
                "finish_pos": int(finish[c]),
            })

    entries = make_entries_df(rows)
    truth = pd.DataFrame({
        "player_no": players,
        "true_dash": true_dash,
        "true_attack": true_attack,
    })
    return entries, truth


@pytest.fixture
def league():
    return synthetic_league(seed=42)
