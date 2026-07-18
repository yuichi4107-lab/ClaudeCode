"""scraper/race_list.py・scraper/race_result.py のテスト。

requests を一切呼ばない: BaseScraper.get を monkeypatch し、
parsers.result_parser はまだ存在しない可能性があるため
race_result._parse_race_result をスタブに差し替えて検証する。
"""

import pytest

from autorace_evaluator.config import settings
from autorace_evaluator.scraper import race_list, race_result
from autorace_evaluator.scraper.base import BaseScraper
from autorace_evaluator.storage import database, repository


# ---------------------------------------------------------- iter_race_urls

def test_iter_race_urls_generates_all_combinations(monkeypatch):
    monkeypatch.setattr(settings, "MAX_RACE_NO", 3)
    urls = list(
        race_list.iter_race_urls(
            "2026-01-01", "2026-01-02", ["kawaguchi", "isesaki"]
        )
    )
    # 2 dates * 2 venues * 3 race_no
    assert len(urls) == 12

    url, meta = urls[0]
    assert meta == {
        "venue": "kawaguchi",
        "date": "2026-01-01",
        "race_no": 1,
        "url": url,
    }
    assert url == settings.BASE_URLS["race_result"].format(
        venue="kawaguchi", date="2026-01-01", race_no=1
    )


def test_iter_race_urls_date_range_inclusive(monkeypatch):
    monkeypatch.setattr(settings, "MAX_RACE_NO", 1)
    urls = list(
        race_list.iter_race_urls("2026-01-01", "2026-01-01", ["kawaguchi"])
    )
    assert len(urls) == 1


def test_iter_race_urls_skips_was_scraped(monkeypatch):
    monkeypatch.setattr(settings, "MAX_RACE_NO", 2)
    conn = database.get_connection(":memory:")
    database.init_db(conn)

    url1 = settings.BASE_URLS["race_result"].format(
        venue="kawaguchi", date="2026-01-01", race_no=1
    )
    repository.log_scrape(conn, url1, status_code=200)

    stats = {}
    urls = list(
        race_list.iter_race_urls(
            "2026-01-01", "2026-01-01", ["kawaguchi"], conn=conn, stats=stats
        )
    )

    assert [m["race_no"] for _, m in urls] == [2]
    assert stats["skipped"] == 1


def test_iter_race_urls_cached_404_on_race1_skips_rest(monkeypatch):
    monkeypatch.setattr(settings, "MAX_RACE_NO", 3)
    conn = database.get_connection(":memory:")
    database.init_db(conn)

    url1 = settings.BASE_URLS["race_result"].format(
        venue="kawaguchi", date="2026-01-01", race_no=1
    )
    repository.log_scrape(conn, url1, status_code=404)

    urls = list(
        race_list.iter_race_urls(
            "2026-01-01", "2026-01-01", ["kawaguchi"], conn=conn
        )
    )
    assert urls == []  # race_no=1 が404済み → 2,3 は probe しない


def test_iter_race_urls_send_skip_rest_stops_day(monkeypatch):
    monkeypatch.setattr(settings, "MAX_RACE_NO", 5)
    gen = race_list.iter_race_urls("2026-01-01", "2026-01-01", ["kawaguchi"])
    url, meta = next(gen)
    assert meta["race_no"] == 1
    with pytest.raises(StopIteration):
        gen.send(True)  # 残りをスキップ → この日この会場ではもう出ない


def test_iter_race_urls_no_probe_ignores_send(monkeypatch):
    monkeypatch.setattr(settings, "MAX_RACE_NO", 3)
    gen = race_list.iter_race_urls(
        "2026-01-01", "2026-01-01", ["kawaguchi"], probe=False
    )
    seen = []
    url, meta = next(gen)
    seen.append(meta["race_no"])
    try:
        while True:
            url, meta = gen.send(True)  # probe=False なので無視される
            seen.append(meta["race_no"])
    except StopIteration:
        pass
    assert seen == [1, 2, 3]


# ------------------------------------------------------------ scrape_races

def test_scrape_races_r1_404_skips_rest_of_day(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "MAX_RACE_NO", 5)
    calls = []

    def fake_get(self, url, params=None, dump_name=None):
        calls.append(url)
        return None

    monkeypatch.setattr(BaseScraper, "get", fake_get)

    db_path = str(tmp_path / "test.db")
    stats = race_result.scrape_races(
        "2026-01-01", "2026-01-01", ["kawaguchi", "isesaki"],
        db_path=db_path, progress=False,
    )

    assert len(calls) == 2  # 各会場でレース1のみ試行
    assert stats == {"fetched": 0, "not_found": 2, "skipped": 0, "errors": 0}


def test_scrape_races_no_probe_tries_all_race_numbers(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "MAX_RACE_NO", 3)
    calls = []

    def fake_get(self, url, params=None, dump_name=None):
        calls.append(url)
        return None

    monkeypatch.setattr(BaseScraper, "get", fake_get)

    db_path = str(tmp_path / "test.db")
    stats = race_result.scrape_races(
        "2026-01-01", "2026-01-01", ["kawaguchi"],
        db_path=db_path, progress=False, probe=False,
    )

    assert len(calls) == 3
    assert stats["not_found"] == 3


def test_scrape_races_404_logged_and_skipped_on_rerun(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "MAX_RACE_NO", 1)
    calls = []

    def fake_get(self, url, params=None, dump_name=None):
        calls.append(url)
        return None

    monkeypatch.setattr(BaseScraper, "get", fake_get)

    db_path = str(tmp_path / "test.db")
    stats1 = race_result.scrape_races(
        "2026-01-01", "2026-01-01", ["kawaguchi"], db_path=db_path, progress=False
    )
    assert stats1["not_found"] == 1
    assert len(calls) == 1

    stats2 = race_result.scrape_races(
        "2026-01-01", "2026-01-01", ["kawaguchi"], db_path=db_path, progress=False
    )
    assert stats2["skipped"] == 1
    assert stats2["not_found"] == 0
    assert len(calls) == 1  # 二回目はHTTPを叩かない


def test_scrape_races_success_upserts_to_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "MAX_RACE_NO", 1)

    def fake_get(self, url, params=None, dump_name=None):
        return "<html>fake</html>"

    def fake_parse(html, url_meta):
        race_id = f"{url_meta['venue']}_{url_meta['date']}_{url_meta['race_no']}"
        return {
            "race": {
                "race_id": race_id,
                "venue": url_meta["venue"],
                "race_date": url_meta["date"],
                "race_no": url_meta["race_no"],
            },
            "entries": [
                {"car_no": 1, "player_no": 111, "player_name": "山田太郎", "finish_pos": 1},
                {"car_no": 2, "player_no": None, "player_name": None, "finish_pos": 2},
            ],
            "payouts": [{"bet_type": "単勝", "combination": "1", "payout": 150}],
        }

    monkeypatch.setattr(BaseScraper, "get", fake_get)
    monkeypatch.setattr(race_result, "_parse_race_result", fake_parse)

    db_path = str(tmp_path / "test.db")
    stats = race_result.scrape_races(
        "2026-01-01", "2026-01-01", ["kawaguchi"], db_path=db_path, progress=False
    )

    assert stats == {"fetched": 1, "not_found": 0, "skipped": 0, "errors": 0}

    conn = database.get_connection(db_path)
    race_id = "kawaguchi_2026-01-01_1"

    race_row = conn.execute(
        "SELECT * FROM races WHERE race_id = ?", (race_id,)
    ).fetchone()
    assert race_row is not None
    assert race_row["venue"] == "kawaguchi"

    entries = conn.execute(
        "SELECT * FROM race_entries WHERE race_id = ? ORDER BY car_no", (race_id,)
    ).fetchall()
    assert len(entries) == 2
    assert entries[0]["player_no"] == 111
    assert entries[1]["player_no"] is None

    player = conn.execute(
        "SELECT * FROM players WHERE player_no = 111"
    ).fetchone()
    assert player is not None
    assert player["player_name"] == "山田太郎"

    payouts = conn.execute(
        "SELECT * FROM payouts WHERE race_id = ?", (race_id,)
    ).fetchall()
    assert len(payouts) == 1

    log_rows = conn.execute("SELECT status_code FROM scrape_log").fetchall()
    assert [r["status_code"] for r in log_rows] == [200]
    conn.close()


def test_scrape_races_parse_error_recorded(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "MAX_RACE_NO", 1)

    def fake_get(self, url, params=None, dump_name=None):
        return "<html>broken</html>"

    def fake_parse(html, url_meta):
        return {"error": "could not find result table"}

    monkeypatch.setattr(BaseScraper, "get", fake_get)
    monkeypatch.setattr(race_result, "_parse_race_result", fake_parse)

    db_path = str(tmp_path / "test.db")
    stats = race_result.scrape_races(
        "2026-01-01", "2026-01-01", ["kawaguchi"], db_path=db_path, progress=False
    )
    assert stats == {"fetched": 0, "not_found": 0, "skipped": 0, "errors": 1}

    conn = database.get_connection(db_path)
    log_rows = conn.execute(
        "SELECT status_code, error_msg FROM scrape_log"
    ).fetchall()
    assert log_rows[0]["status_code"] == 0
    assert "could not find result table" in log_rows[0]["error_msg"]
    conn.close()
