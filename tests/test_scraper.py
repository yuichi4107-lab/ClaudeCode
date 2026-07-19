"""scraper/race_list.py・scraper/race_result.py のテスト。

requests を一切呼ばない: BaseScraper 互換の FakeScraper を注入し、
カレンダーAPI・RaceResult/OtherRaceInfo API の応答を辞書で差し替える。
"""

import json
from pathlib import Path

import pytest

from autorace_evaluator.config import settings
from autorace_evaluator.scraper import race_list
from autorace_evaluator.scraper.race_result import scrape_races
from autorace_evaluator.storage import database, repository

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "autorace"


def _load_fixture(name):
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


def _calendar_json(entries):
    """entries = [(place_code, place_key, date, final_race_no), ...]"""
    blocks: dict[int, dict] = {}
    for place_code, place_key, date, final_no in entries:
        block = blocks.setdefault(place_code, {
            "placeCode": place_code, "placeKey": place_key, "calendar": [],
        })
        block["calendar"].append({
            "date": date,
            "race": {"finalRaceNo": final_no, "title": "テスト開催"},
        })
    return {"result": "Success", "errors": [], "body": list(blocks.values())}


_NO_DATA = {"result": "Failure",
            "errors": [{"code": "4101", "message": "レスポンス件数0件"}],
            "body": []}
_CANCELLED = {"result": "Failure",
              "errors": [{"code": "4200", "message": "開催中止"}],
              "body": []}


class FakeScraper:
    """BaseScraper 互換のスタブ。(placeCode, raceDate, raceNo) で応答を引く。"""

    def __init__(self, calendar=None, results=None, others=None):
        self.calendar = calendar
        self.results = results or {}
        self.others = others or {}
        self.get_json_calls = []
        self.post_json_calls = []

    def get_json(self, url, params=None, dump_name=None):
        self.get_json_calls.append((url, params))
        if self.calendar is None:
            raise RuntimeError("calendar unavailable")
        return self.calendar

    def post_json(self, url, payload, dump_name=None):
        self.post_json_calls.append((url, dict(payload)))
        key = (payload["placeCode"], payload["raceDate"], payload["raceNo"])
        if url == settings.BASE_URLS["api_race_result"]:
            return self.results.get(key, _NO_DATA)
        if url == settings.BASE_URLS["api_other_race_info"]:
            return self.others.get(key, _NO_DATA)
        raise AssertionError(f"unexpected url: {url}")


# --------------------------------------------------------- iter_meeting_days

def test_iter_meeting_days_from_calendar():
    cal = _calendar_json([
        (2, "kawaguchi", "2026-01-01", 12),
        (2, "kawaguchi", "2026-01-02", 12),
        (3, "isesaki", "2026-01-01", 8),
        (3, "isesaki", "2026-01-05", 8),  # 期間外
    ])
    scraper = FakeScraper(calendar=cal)
    days = race_list.iter_meeting_days(
        "2026-01-01", "2026-01-03", ["kawaguchi", "isesaki"], scraper)
    assert days == [
        ("isesaki", "2026-01-01", 8),
        ("kawaguchi", "2026-01-01", 12),
        ("kawaguchi", "2026-01-02", 12),
    ]


def test_iter_meeting_days_unknown_final_race_no():
    cal = _calendar_json([(2, "kawaguchi", "2026-01-01", "")])
    scraper = FakeScraper(calendar=cal)
    days = race_list.iter_meeting_days(
        "2026-01-01", "2026-01-01", ["kawaguchi"], scraper)
    assert days == [("kawaguchi", "2026-01-01", None)]


def test_iter_meeting_days_detects_kawaguchi2():
    # placeCode=12 は placeKey が "kawaguchi" でも kawaguchi2 として扱う
    cal = _calendar_json([(12, "kawaguchi", "2026-01-01", 8)])
    scraper = FakeScraper(calendar=cal)
    days = race_list.iter_meeting_days(
        "2026-01-01", "2026-01-01", ["kawaguchi"], scraper)
    assert days == [("kawaguchi2", "2026-01-01", 8)]


def test_iter_meeting_days_fallback_when_calendar_unavailable():
    scraper = FakeScraper(calendar=None)  # get_json が例外
    days = race_list.iter_meeting_days(
        "2026-01-01", "2026-01-02", ["kawaguchi"], scraper)
    assert days == [
        ("kawaguchi", "2026-01-01", None),
        ("kawaguchi", "2026-01-02", None),
    ]


def test_month_range_spans_years():
    months = list(race_list._month_range("2025-11-15", "2026-02-01"))
    assert months == ["2025-11", "2025-12", "2026-01", "2026-02"]


# ------------------------------------------------------------ scrape_races

def _fake_for_one_day(final_no=2, date="2026-01-01"):
    result_fx = _load_fixture("synthetic_result_api.json")
    other_fx = _load_fixture("synthetic_other_api.json")
    cal = _calendar_json([(2, "kawaguchi", date, final_no)])
    results = {(2, date, no): result_fx for no in range(1, (final_no or 2) + 1)}
    others = {(2, date, no): other_fx for no in range(1, (final_no or 2) + 1)}
    return FakeScraper(calendar=cal, results=results, others=others)


def test_scrape_races_fetches_and_saves(tmp_path):
    db_path = str(tmp_path / "test.db")
    scraper = _fake_for_one_day(final_no=2)

    stats = scrape_races(
        "2026-01-01", "2026-01-01", ["kawaguchi"],
        db_path=db_path, progress=False, scraper=scraper,
    )
    assert stats["fetched"] == 2
    assert stats["errors"] == 0

    conn = database.get_connection(db_path)
    try:
        races = conn.execute("SELECT * FROM races ORDER BY race_no").fetchall()
        assert [r["race_no"] for r in races] == [1, 2]
        assert races[0]["track_status"] == "良走路"
        assert races[0]["trial_track_status"] == "良走路"
        assert races[0]["meeting_id"] == "kawaguchi_2026-07-16"
        assert races[0]["distance"] == 3100

        entries = conn.execute(
            "SELECT * FROM race_entries WHERE race_id = 'kawaguchi_2026-01-01_1' "
            "ORDER BY car_no").fetchall()
        assert len(entries) == 7
        winner = next(e for e in entries if e["finish_pos"] == 1)
        assert winner["trial_time"] == 3.31
        assert winner["st"] == 0.05
        assert winner["handicap"] == 10

        payouts = conn.execute(
            "SELECT COUNT(*) AS n FROM payouts "
            "WHERE race_id = 'kawaguchi_2026-01-01_1'").fetchone()
        assert payouts["n"] > 0
    finally:
        conn.close()


def test_scrape_races_second_run_skips(tmp_path):
    db_path = str(tmp_path / "test.db")
    scraper = _fake_for_one_day(final_no=2)
    scrape_races("2026-01-01", "2026-01-01", ["kawaguchi"],
                 db_path=db_path, progress=False, scraper=scraper)

    scraper2 = _fake_for_one_day(final_no=2)
    stats = scrape_races("2026-01-01", "2026-01-01", ["kawaguchi"],
                         db_path=db_path, progress=False, scraper=scraper2)
    assert stats["skipped"] == 2
    assert stats["fetched"] == 0
    assert scraper2.post_json_calls == []  # API は一切呼ばれない


def test_scrape_races_probing_stops_on_no_data(tmp_path):
    """最終レース番号不明時、4101 応答で残りレース番号を打ち切る。"""
    db_path = str(tmp_path / "test.db")
    result_fx = _load_fixture("synthetic_result_api.json")
    other_fx = _load_fixture("synthetic_other_api.json")
    cal = _calendar_json([(2, "kawaguchi", "2026-01-01", "")])  # final 不明
    results = {(2, "2026-01-01", no): result_fx for no in (1, 2, 3)}
    others = {(2, "2026-01-01", no): other_fx for no in (1, 2, 3)}
    scraper = FakeScraper(calendar=cal, results=results, others=others)

    stats = scrape_races("2026-01-01", "2026-01-01", ["kawaguchi"],
                         db_path=db_path, progress=False, scraper=scraper)
    assert stats["fetched"] == 3
    assert stats["not_found"] == 1  # 4R で 4101 → 5R 以降は試さない
    race_result_calls = [
        p["raceNo"] for u, p in scraper.post_json_calls
        if u == settings.BASE_URLS["api_race_result"]
    ]
    assert race_result_calls == [1, 2, 3, 4]


def test_scrape_races_cancelled_race_continues_day(tmp_path):
    """4200(中止)は cancelled に数え、同日の残りレースは試し続ける。"""
    db_path = str(tmp_path / "test.db")
    result_fx = _load_fixture("synthetic_result_api.json")
    other_fx = _load_fixture("synthetic_other_api.json")
    cal = _calendar_json([(2, "kawaguchi", "2026-01-01", 3)])
    results = {
        (2, "2026-01-01", 1): result_fx,
        (2, "2026-01-01", 2): _CANCELLED,
        (2, "2026-01-01", 3): result_fx,
    }
    others = {(2, "2026-01-01", no): other_fx for no in (1, 3)}
    scraper = FakeScraper(calendar=cal, results=results, others=others)

    stats = scrape_races("2026-01-01", "2026-01-01", ["kawaguchi"],
                         db_path=db_path, progress=False, scraper=scraper)
    assert stats["fetched"] == 2
    assert stats["cancelled"] == 1


def test_scrape_races_logs_scrape_urls(tmp_path):
    db_path = str(tmp_path / "test.db")
    scraper = _fake_for_one_day(final_no=1)
    scrape_races("2026-01-01", "2026-01-01", ["kawaguchi"],
                 db_path=db_path, progress=False, scraper=scraper)

    conn = database.get_connection(db_path)
    try:
        row = conn.execute("SELECT * FROM scrape_log").fetchone()
        expected_url = settings.BASE_URLS["race_result_page"].format(
            venue="kawaguchi", date="2026-01-01", race_no=1)
        assert row["url"] == expected_url
        assert row["status_code"] == 200
    finally:
        conn.close()


def test_was_scraped_semantics(tmp_path):
    conn = database.get_connection(":memory:")
    database.init_db(conn)
    repository.log_scrape(conn, "u200", status_code=200)
    repository.log_scrape(conn, "u404", status_code=404)
    repository.log_scrape(conn, "u0", status_code=0, error_msg="boom")
    assert repository.was_scraped(conn, "u200")
    assert repository.was_scraped(conn, "u404")
    assert not repository.was_scraped(conn, "u0")  # エラーは再試行対象
    assert not repository.was_scraped(conn, "unknown")
