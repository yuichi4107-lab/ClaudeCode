"""scraper/race_program.py のテスト(requests 不使用、FakeScraper 注入)。"""

import json
from pathlib import Path

from autorace_evaluator.config import settings
from autorace_evaluator.scraper.race_program import scrape_programs
from autorace_evaluator.scraper.race_result import scrape_races
from autorace_evaluator.storage import database
from tests.test_scraper import FakeScraper, _calendar_json, _NO_DATA

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "autorace"


def _load_fixture(name):
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


class FakeProgramScraper(FakeScraper):
    """FakeScraper に Program API 応答を追加したスタブ。"""

    def __init__(self, programs=None, **kwargs):
        super().__init__(**kwargs)
        self.programs = programs or {}

    def post_json(self, url, payload, dump_name=None):
        if url == settings.BASE_URLS["api_program"]:
            self.post_json_calls.append((url, dict(payload)))
            key = (payload["placeCode"], payload["raceDate"], payload["raceNo"])
            return self.programs.get(key, _NO_DATA)
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


def test_scrape_programs_updates_entries(tmp_path):
    db_path = str(tmp_path / "test.db")
    _seed_results(db_path)

    program_fx = _load_fixture("synthetic_program_api.json")
    scraper = FakeProgramScraper(programs={
        (2, "2026-01-01", 1): program_fx,
        (2, "2026-01-01", 2): program_fx,
    })
    stats = scrape_programs("2026-01-01", "2026-01-01", ["kawaguchi"],
                            db_path=db_path, progress=False, scraper=scraper)
    assert stats["fetched"] == 2
    assert stats["errors"] == 0
    assert stats["rows_updated"] == 14  # 7行 × 2レース

    conn = database.get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM race_entries WHERE race_id='kawaguchi_2026-01-01_1' "
            "AND car_no=3").fetchone()
        assert row["bike_class"] == "2級車"
        assert row["graduation_code"] == 38
        assert row["age"] == 22
        # 結果由来列は保持されている
        assert row["trial_time"] is not None
    finally:
        conn.close()


def test_scrape_programs_second_run_skips(tmp_path):
    db_path = str(tmp_path / "test.db")
    _seed_results(db_path)
    program_fx = _load_fixture("synthetic_program_api.json")
    programs = {(2, "2026-01-01", no): program_fx for no in (1, 2)}

    scrape_programs("2026-01-01", "2026-01-01", ["kawaguchi"], db_path=db_path,
                    progress=False, scraper=FakeProgramScraper(programs=programs))
    scraper2 = FakeProgramScraper(programs=programs)
    stats = scrape_programs("2026-01-01", "2026-01-01", ["kawaguchi"],
                            db_path=db_path, progress=False, scraper=scraper2)
    assert stats["skipped"] == 2
    assert stats["fetched"] == 0
    assert scraper2.post_json_calls == []


def test_scrape_programs_no_data_logged_as_not_found(tmp_path):
    db_path = str(tmp_path / "test.db")
    _seed_results(db_path, final_no=1)
    scraper = FakeProgramScraper(programs={})  # 全て 4101
    stats = scrape_programs("2026-01-01", "2026-01-01", ["kawaguchi"],
                            db_path=db_path, progress=False, scraper=scraper)
    assert stats["not_found"] == 1
    assert stats["fetched"] == 0


def test_scrape_programs_without_results_is_noop(tmp_path):
    """races テーブルが空なら何もリクエストしない。"""
    db_path = str(tmp_path / "test.db")
    scraper = FakeProgramScraper()
    stats = scrape_programs("2026-01-01", "2026-01-01", ["kawaguchi"],
                            db_path=db_path, progress=False, scraper=scraper)
    assert stats == {"fetched": 0, "not_found": 0, "skipped": 0,
                     "errors": 0, "rows_updated": 0}
    assert scraper.post_json_calls == []
