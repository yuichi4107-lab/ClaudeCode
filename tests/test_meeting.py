import pandas as pd

from autorace_evaluator.metrics.meeting import derive_meeting_ids, update_meeting_ids
from autorace_evaluator.storage import database, repository


def _races(rows):
    return pd.DataFrame(rows, columns=["race_id", "venue", "race_date"])


def test_consecutive_days_form_one_meeting():
    races = _races([
        ("kawaguchi_2026-01-01_1", "kawaguchi", "2026-01-01"),
        ("kawaguchi_2026-01-02_1", "kawaguchi", "2026-01-02"),
        ("kawaguchi_2026-01-03_1", "kawaguchi", "2026-01-03"),
    ])
    ids = derive_meeting_ids(races)
    assert set(ids.values()) == {"kawaguchi_2026-01-01"}


def test_gap_day_splits_meetings():
    races = _races([
        ("kawaguchi_2026-01-01_1", "kawaguchi", "2026-01-01"),
        ("kawaguchi_2026-01-02_1", "kawaguchi", "2026-01-02"),
        # 1/3 が飛ぶ(順延など) → 1/4 からは別節
        ("kawaguchi_2026-01-04_1", "kawaguchi", "2026-01-04"),
    ])
    ids = derive_meeting_ids(races)
    assert ids["kawaguchi_2026-01-02_1"] == "kawaguchi_2026-01-01"
    assert ids["kawaguchi_2026-01-04_1"] == "kawaguchi_2026-01-04"


def test_venues_are_independent():
    races = _races([
        ("kawaguchi_2026-01-01_1", "kawaguchi", "2026-01-01"),
        ("isesaki_2026-01-01_1", "isesaki", "2026-01-01"),
        ("isesaki_2026-01-02_1", "isesaki", "2026-01-02"),
    ])
    ids = derive_meeting_ids(races)
    assert ids["kawaguchi_2026-01-01_1"] == "kawaguchi_2026-01-01"
    assert ids["isesaki_2026-01-02_1"] == "isesaki_2026-01-01"


def test_same_day_multiple_races_share_meeting():
    races = _races([
        ("kawaguchi_2026-01-01_1", "kawaguchi", "2026-01-01"),
        ("kawaguchi_2026-01-01_2", "kawaguchi", "2026-01-01"),
    ])
    ids = derive_meeting_ids(races)
    assert ids["kawaguchi_2026-01-01_1"] == ids["kawaguchi_2026-01-01_2"]


def test_update_meeting_ids_writes_to_db():
    conn = database.get_connection(":memory:")
    database.init_db(conn)
    for d in ("2026-01-01", "2026-01-02"):
        repository.upsert_race(conn, {
            "race_id": f"kawaguchi_{d}_1", "venue": "kawaguchi",
            "race_date": d, "race_no": 1,
        })
    n = update_meeting_ids(conn)
    assert n == 2
    rows = conn.execute("SELECT race_id, meeting_id FROM races").fetchall()
    assert {r[1] for r in rows} == {"kawaguchi_2026-01-01"}
