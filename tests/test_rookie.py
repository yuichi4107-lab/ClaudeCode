"""metrics/rookie.py(新人・2級車成績)のテスト。"""

import numpy as np
import pandas as pd

from autorace_evaluator.metrics import rookie as rookie_mod
from tests.conftest import make_entries_df, synthetic_league


def _rookie_rows(player_no, n, grad=39, start_day=1, trial_start=3.45,
                 trial_step=0.0, st=0.12, finish=4):
    """1選手分の2級車出走行を日付順に作る。"""
    rows = []
    for i in range(n):
        rows.append({
            "race_id": f"kawaguchi_2026-01-{start_day + i:02d}_1",
            "race_date": f"2026-01-{start_day + i:02d}",
            "race_no": 1,
            "car_no": 1,
            "player_no": player_no,
            "bike_class": "2級車",
            "graduation_code": grad,
            "age": 20,
            "trial_time": round(trial_start + trial_step * i, 3),
            "st": st,
            "finish_pos": finish,
        })
    return rows


def test_no_program_data_returns_empty():
    entries, _ = synthetic_league(seed=1, n_players=10, n_races=50)
    entries = entries.drop(columns=["bike_class"])
    roster = rookie_mod.rookie_roster(entries)
    assert roster.empty
    table, diag = rookie_mod.compute_rookie(entries)
    assert table.empty


def test_roster_by_recent_term():
    # ベテラン(30期・多数走)と新人(39期)を混在させる
    rows = []
    for p in range(1, 6):
        for i in range(40):
            rows.append({
                "race_id": f"kawaguchi_2026-{1 + i // 28:02d}-{i % 28 + 1:02d}_{p}",
                "race_date": f"2026-{1 + i // 28:02d}-{i % 28 + 1:02d}",
                "car_no": p, "player_no": p, "graduation_code": 30,
                "bike_class": "1級車",
            })
    rows += _rookie_rows(101, 10, grad=39)
    entries = make_entries_df(rows)

    roster = rookie_mod.rookie_roster(entries, recent_terms=2, max_debut_races=5)
    assert set(roster["player_no"]) == {101}
    assert roster.iloc[0]["definition"] == "term"


def test_roster_by_debut_races():
    rows = []
    for p in range(1, 6):
        for i in range(40):
            rows.append({
                "race_id": f"kawaguchi_2026-{1 + i // 28:02d}-{i % 28 + 1:02d}_{p}",
                "race_date": f"2026-{1 + i // 28:02d}-{i % 28 + 1:02d}",
                "car_no": p, "player_no": p, "graduation_code": 38,
                "bike_class": "1級車",
            })
    # 期別欠損だが出走10走のみ → debut 判定
    rookie_rows = _rookie_rows(102, 10, grad=None)
    for r in rookie_rows:
        r["graduation_code"] = None
    entries = make_entries_df(rows + rookie_rows)

    roster = rookie_mod.rookie_roster(entries, recent_terms=0, max_debut_races=30)
    assert 102 in set(roster["player_no"])
    row = roster[roster["player_no"] == 102].iloc[0]
    assert "debut" in row["definition"]


def test_trial_trend_recovery():
    """単調に試走タイムが改善する新人の trial_trend が負になる。"""
    entries, _ = synthetic_league(seed=3, n_players=30, n_races=600)
    entries["graduation_code"] = 30
    entries["bike_class"] = "1級車"
    improving = _rookie_rows(201, 12, grad=39, trial_start=3.50, trial_step=-0.01)
    flat = _rookie_rows(202, 12, grad=39, trial_start=3.45, trial_step=0.0)
    entries = pd.concat([entries, make_entries_df(improving + flat)],
                        ignore_index=True)

    table, _ = rookie_mod.compute_rookie(entries)
    t = table.set_index("player_no")
    assert t.loc[201, "trial_trend"] < -0.005
    assert abs(t.loc[202, "trial_trend"]) < 0.005


def test_win_and_top3_rates():
    rows = _rookie_rows(301, 4, finish=1) + _rookie_rows(301, 4, start_day=10, finish=5)
    entries = make_entries_df(rows)
    table, _ = rookie_mod.compute_rookie(entries, min_races=5)
    row = table[table["player_no"] == 301].iloc[0]
    assert row["n_rookie"] == 8
    assert abs(row["win_rate"] - 0.5) < 1e-9
    assert abs(row["top3_rate"] - 0.5) < 1e-9


def test_min_races_gives_nan_score():
    rows = _rookie_rows(401, 3)
    entries = make_entries_df(rows)
    table, _ = rookie_mod.compute_rookie(entries, min_races=5)
    row = table[table["player_no"] == 401].iloc[0]
    assert pd.isna(row["rookie_score"])


def test_build_rookie_report_shape():
    entries, _ = synthetic_league(seed=4, n_players=20, n_races=200)
    entries["graduation_code"] = 30
    entries["bike_class"] = "1級車"
    entries = pd.concat(
        [entries, make_entries_df(_rookie_rows(501, 10, grad=39))],
        ignore_index=True)
    rep = rookie_mod.build_rookie_report(entries)
    assert list(rep["table"].columns) == rookie_mod.COLUMN_ORDER
    assert 501 in set(rep["table"]["player_no"])
