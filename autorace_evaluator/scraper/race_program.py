"""出走表(Program)の収集。

races テーブルに保存済みのレースを対象に Program API を叩き、
race_entries の Program 由来列(車級・期別・級班・年齢・連対率)を UPDATE する。
結果収集(scrape_races)が先行している前提のため、開催探索(カレンダー/probe)は
不要で、バックフィルと差分収集が同一コードで済む。

scrape_log のキーは settings.BASE_URLS["race_program_page"] の疑似URLを使い、
race_result.py と同じ再開可能設計(4101 は 404 相当で記録して再訪しない)。
"""

from __future__ import annotations

import logging

from tqdm import tqdm

from autorace_evaluator.config import settings
from autorace_evaluator.scraper.base import BaseScraper
from autorace_evaluator.storage import database, repository

logger = logging.getLogger(__name__)


def _parse_api_program(program_json: dict, url_meta: dict) -> dict:
    """parsers/program_parser.py への遅延import経由の呼び出し(テストで差し替え可能)。"""
    from autorace_evaluator.parsers.program_parser import parse_api_program

    return parse_api_program(program_json, url_meta)


def scrape_programs(
    from_date: str,
    to_date: str,
    venues: list[str],
    db_path: str | None = None,
    use_cache: bool = True,
    dump_dir: str | None = None,
    progress: bool = True,
    scraper: BaseScraper | None = None,
) -> dict:
    """期間内の保存済みレースについて出走表を収集し、race_entries を更新する。

    戻り値: {"fetched": n, "not_found": n, "skipped": n, "errors": n,
             "rows_updated": n}
    """
    conn = database.get_connection(db_path)
    database.init_db(conn)

    if scraper is None:
        scraper = BaseScraper(use_cache=use_cache, dump_dir=dump_dir)

    allowed = set(venues) | {settings.TWICE_VENUE_SLUG}
    races = [
        r for r in repository.get_races(conn, from_date, to_date)
        if r["venue"] in allowed
    ]
    logger.info("出走表収集の対象レース数: %d", len(races))

    stats = {"fetched": 0, "not_found": 0, "skipped": 0, "errors": 0,
             "rows_updated": 0}

    pbar = tqdm(desc="program", unit="race", disable=not progress)
    try:
        for race in races:
            venue = race["venue"]
            date_str = race["race_date"]
            race_no = race["race_no"]
            url = settings.BASE_URLS["race_program_page"].format(
                venue=venue, date=date_str, race_no=race_no
            )

            if repository.was_scraped(conn, url):
                stats["skipped"] += 1
                continue

            pbar.update(1)
            payload = {
                "placeCode": settings.PLACE_CODES[venue],
                "raceDate": date_str,
                "raceNo": race_no,
            }

            try:
                program_json = scraper.post_json(
                    settings.BASE_URLS["api_program"], payload,
                    dump_name=f"{venue}_{date_str}_{race_no}.program",
                )
            except Exception as exc:  # noqa: BLE001 - 最終失敗を記録して継続する
                logger.warning("Fetch failed: %s (%s)", url, exc)
                repository.log_scrape(conn, url, status_code=0, error_msg=str(exc))
                stats["errors"] += 1
                continue

            if program_json is None:
                repository.log_scrape(conn, url, status_code=404, error_msg="HTTP 404")
                stats["not_found"] += 1
                continue

            meta = {"venue": venue, "date": date_str, "race_no": race_no, "url": url}
            result = _parse_api_program(program_json, meta)
            error = result.get("error")
            if error:
                code = result.get("error_code")
                if code in (settings.API_CODE_NO_DATA, settings.API_CODE_CANCELLED):
                    repository.log_scrape(
                        conn, url, status_code=404, error_msg=f"データなし({code})")
                    stats["not_found"] += 1
                else:
                    logger.warning("Parse failed: %s (%s)", url, error)
                    repository.log_scrape(conn, url, status_code=0, error_msg=str(error))
                    stats["errors"] += 1
                continue

            for w in result.get("warnings", []):
                logger.info("Program warning %s: %s", url, w)

            updated = repository.update_entry_program_fields(
                conn, race["race_id"], result["entries"])
            if updated == 0:
                logger.info("Program: 突合0行 %s", url)

            repository.log_scrape(conn, url, status_code=200)
            stats["fetched"] += 1
            stats["rows_updated"] += updated
    finally:
        pbar.close()
        conn.close()

    return stats
