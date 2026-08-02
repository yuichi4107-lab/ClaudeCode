"""model/predict_service.py のオッズ統合部分のテスト(モデル学習は伴わない)。"""

import json
from pathlib import Path

import numpy as np
import pandas as pd

from autorace_evaluator.config import settings
from autorace_evaluator.model import predict_service as ps
from autorace_evaluator.storage import database, repository
from tests.test_scraper import FakeScraper, _NO_DATA

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "autorace"
REAL_DIR = FIXTURES_DIR / "real"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class FakeDayScraper(FakeScraper):
    """1R のみ出走表・補足情報・オッズを返すスタブ(2R 以降は 4101)。"""

    def __init__(self, program=None, other=None, odds=None):
        super().__init__()
        self.program = program
        self.other = other
        self.odds = odds

    def post_json(self, url, payload, dump_name=None):
        self.post_json_calls.append((url, dict(payload)))
        if payload["raceNo"] != 1:
            return _NO_DATA
        if url == settings.BASE_URLS["api_program"]:
            return self.program
        if url == settings.BASE_URLS["api_other_race_info"]:
            return self.other
        if url == settings.BASE_URLS["api_odds"]:
            return self.odds
        raise AssertionError(f"unexpected url: {url}")


def test_fetch_program_entries_uses_odds_trial_time_and_odds_map():
    scraper = FakeDayScraper(
        program=_load(FIXTURES_DIR / "synthetic_program_api.json"),
        other=_load(FIXTURES_DIR / "synthetic_other_api.json"),
        odds=_load(REAL_DIR / "hamamatsu_2026-08-02_1.odds.json"),
    )
    rows, odds_by_race = ps._fetch_program_entries(
        scraper, "hamamatsu", "2026-08-02")

    race_id = "hamamatsu_2026-08-02_1"
    # 出走表に試走タイムが無くても、オッズAPIの trialTime で埋まる
    trials = {r["car_no"]: r["trial_time"] for r in rows}
    assert trials[2] == 3.41
    assert trials[5] == 3.43

    info = odds_by_race[race_id]
    assert info["status_code"] == 0
    assert info["updated_at"] == "2026-08-02 10:29:04"
    assert info["exacta"][(1, 2)] == 34.9
    assert info["win"][4] == 3.5


def test_fetch_program_entries_without_odds_keeps_going():
    """オッズAPIが 4101 でも出走表だけで予想行を組める。"""
    scraper = FakeDayScraper(
        program=_load(FIXTURES_DIR / "synthetic_program_api.json"),
        other=_load(FIXTURES_DIR / "synthetic_other_api.json"),
        odds=_NO_DATA,
    )
    rows, odds_by_race = ps._fetch_program_entries(
        scraper, "hamamatsu", "2026-08-02")
    assert len(rows) == 6  # 欠車1名を除いた6行
    assert odds_by_race == {}


def test_attach_odds_adds_odds_and_ev_columns():
    exacta = pd.DataFrame({
        "race_id": ["r1", "r1"],
        "first": [1, 2],
        "second": [2, 1],
        "prob": [0.3, 0.2],
    })
    odds_by_race = {"r1": {"status_code": 1, "updated_at": "t",
                           "exacta": {(1, 2): 5.0}, "win": {}}}
    out = ps._attach_odds(exacta, odds_by_race)
    assert out.loc[0, "odds"] == 5.0
    assert abs(out.loc[0, "ev"] - 1.5) < 1e-12
    assert np.isnan(out.loc[1, "odds"])  # オッズ欠測は NaN
    assert np.isnan(out.loc[1, "ev"])


def test_attach_odds_without_any_odds():
    exacta = pd.DataFrame({
        "race_id": ["r1"], "first": [1], "second": [2], "prob": [0.3]})
    out = ps._attach_odds(exacta, {})
    assert out["odds"].isna().all()
    assert out["ev"].isna().all()


def test_load_odds_from_db(tmp_path):
    db_path = str(tmp_path / "test.db")
    conn = database.get_connection(db_path)
    try:
        database.init_db(conn)
        repository.upsert_race(conn, {
            "race_id": "kawaguchi_2026-01-01_1", "venue": "kawaguchi",
            "race_date": "2026-01-01", "race_no": 1})
        repository.upsert_exacta_odds(conn, "kawaguchi_2026-01-01_1", [
            {"first": 1, "second": 2, "odds": 12.5,
             "status_code": 1, "updated_at": "2026-01-01 16:00:00"},
            {"first": 2, "second": 1, "odds": None,
             "status_code": 1, "updated_at": "2026-01-01 16:00:00"},
        ])
        odds_by_race = ps._load_odds_from_db(conn, "2026-01-01", "kawaguchi")
        other_venue = ps._load_odds_from_db(conn, "2026-01-01", "sanyou")
    finally:
        conn.close()

    info = odds_by_race["kawaguchi_2026-01-01_1"]
    assert info["status_code"] == 1
    assert info["updated_at"] == "2026-01-01 16:00:00"
    assert info["exacta"] == {(1, 2): 12.5}  # NULL オッズは含めない
    assert other_venue == {}
