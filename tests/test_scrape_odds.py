"""scraper/race_odds.py のテスト(requests 不使用、FakeScraper 注入)。"""

import json
from pathlib import Path

from autorace_evaluator.config import settings
from autorace_evaluator.scraper.race_odds import scrape_odds
from autorace_evaluator.scraper.race_result import scrape_races
from autorace_evaluator.storage import database
from tests.test_scraper import FakeScraper, _calendar_json, _NO_DATA

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "autorace"
REAL_DIR = FIXTURES_DIR / "real"


def _load_fixture(name):
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


def _load_real(name):
    return json.loads((REAL_DIR / name).read_text(encoding="utf-8"))


class FakeOddsScraper(FakeScraper):
    """FakeScraper に Odds API 応答を追加したスタブ。"""

    def __init__(self, odds=None, **kwargs):
        super().__init__(**kwargs)
        self.odds = odds or {}

    def post_json(self, url, payload, dump_name=None):
        if url == settings.BASE_URLS["api_odds"]:
            self.post_json_calls.append((url, dict(payload)))
            key = (payload["placeCode"], payload["raceDate"], payload["raceNo"])
            return self.odds.get(key, _NO_DATA)
        return super().post_json(url, payload, dump_name=dump_name)


def _seed_results(db_path, date="2026-01-01", final_no=2):
    """結果収集を先行実行して races/race_entries を作る。"""
    result_fx = _load_fixture("synthetic_result_api.json")
    other_fx = _load_fixture("synthetic_other_api.json")
    cal = _calendar_json([(2, "kawaguchi", date, final_no)])
    results = {(2, date, no): result_fx for no in range(1, final_no + 1)}
    others = {(2, date, no): other_fx for no in range(1, final_no + 1)}
    scraper = FakeScraper(calendar=cal, results=results, others=others)
    scrape_races(date, date, ["kawaguchi"], db_path=db_path,
                 progress=False, scraper=scraper)


def test_scrape_odds_saves_rows(tmp_path):
    db_path = str(tmp_path / "test.db")
    _seed_results(db_path, final_no=1)

    final_fx = _load_real("sanyou_2026-07-17_8.odds.json")
    scraper = FakeOddsScraper(odds={(2, "2026-01-01", 1): final_fx})
    stats = scrape_odds("2026-01-01", "2026-01-01", ["kawaguchi"],
                        db_path=db_path, progress=False, scraper=scraper)
    assert stats["fetched"] == 1
    assert stats["errors"] == 0
    assert stats["rows_updated"] == 36  # 2連単30通り + 単勝6車

    conn = database.get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM exacta_odds WHERE race_id='kawaguchi_2026-01-01_1' "
            "AND first=2 AND second=6").fetchone()
        assert row["odds"] == 23.1
        assert row["status_code"] == 1
        assert row["updated_at"] == "2026-08-02 10:29:00"

        win = conn.execute(
            "SELECT * FROM win_odds WHERE race_id='kawaguchi_2026-01-01_1' "
            "AND car_no=6").fetchone()
        assert win["odds"] == 1.2
    finally:
        conn.close()


def test_scrape_odds_final_is_logged_and_skipped_next_run(tmp_path):
    """最終オッズ(statusCode=1)は完了記録され、2回目は再取得しない。"""
    db_path = str(tmp_path / "test.db")
    _seed_results(db_path, final_no=2)
    final_fx = _load_real("sanyou_2026-07-17_8.odds.json")
    odds = {(2, "2026-01-01", no): final_fx for no in (1, 2)}

    scrape_odds("2026-01-01", "2026-01-01", ["kawaguchi"], db_path=db_path,
                progress=False, scraper=FakeOddsScraper(odds=odds))

    scraper2 = FakeOddsScraper(odds=odds)
    stats = scrape_odds("2026-01-01", "2026-01-01", ["kawaguchi"],
                        db_path=db_path, progress=False, scraper=scraper2)
    assert stats["skipped"] == 2
    assert stats["fetched"] == 0
    assert scraper2.post_json_calls == []


def test_scrape_odds_intermediate_is_revisited(tmp_path):
    """中間オッズ(statusCode=0)は完了記録せず、次回も取得しにいく。"""
    db_path = str(tmp_path / "test.db")
    _seed_results(db_path, final_no=1)
    live_fx = _load_real("hamamatsu_2026-08-02_1.odds.json")
    odds = {(2, "2026-01-01", 1): live_fx}

    stats1 = scrape_odds("2026-01-01", "2026-01-01", ["kawaguchi"], db_path=db_path,
                         progress=False, scraper=FakeOddsScraper(odds=odds))
    assert stats1["fetched"] == 1

    conn = database.get_connection(db_path)
    try:
        assert conn.execute("SELECT COUNT(*) AS n FROM scrape_log "
                            "WHERE url LIKE '%RaceOdds%'").fetchone()["n"] == 0
        row = conn.execute(
            "SELECT * FROM exacta_odds WHERE race_id='kawaguchi_2026-01-01_1' "
            "AND first=1 AND second=2").fetchone()
        assert row["odds"] == 34.9
        assert row["status_code"] == 0
    finally:
        conn.close()

    # 2回目: skip されず再取得され、最終オッズで上書きされる
    final_fx = _load_real("sanyou_2026-07-17_8.odds.json")
    scraper2 = FakeOddsScraper(odds={(2, "2026-01-01", 1): final_fx})
    stats2 = scrape_odds("2026-01-01", "2026-01-01", ["kawaguchi"],
                         db_path=db_path, progress=False, scraper=scraper2)
    assert stats2["skipped"] == 0
    assert stats2["fetched"] == 1
    assert scraper2.post_json_calls

    conn = database.get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM exacta_odds WHERE race_id='kawaguchi_2026-01-01_1' "
            "AND first=2 AND second=6").fetchone()
        assert row["odds"] == 23.1
        assert row["status_code"] == 1
    finally:
        conn.close()


def test_scrape_odds_no_data_logged_as_not_found(tmp_path):
    db_path = str(tmp_path / "test.db")
    _seed_results(db_path, final_no=1)
    scraper = FakeOddsScraper(odds={})  # 全て 4101
    stats = scrape_odds("2026-01-01", "2026-01-01", ["kawaguchi"],
                        db_path=db_path, progress=False, scraper=scraper)
    assert stats["not_found"] == 1
    assert stats["fetched"] == 0


def test_scrape_odds_without_results_is_noop(tmp_path):
    """races テーブルが空なら何もリクエストしない。"""
    db_path = str(tmp_path / "test.db")
    scraper = FakeOddsScraper()
    stats = scrape_odds("2026-01-01", "2026-01-01", ["kawaguchi"],
                        db_path=db_path, progress=False, scraper=scraper)
    assert stats == {"fetched": 0, "not_found": 0, "skipped": 0,
                     "errors": 0, "rows_updated": 0}
    assert scraper.post_json_calls == []
