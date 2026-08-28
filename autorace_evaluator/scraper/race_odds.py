"""オッズ(Odds)の収集。

races テーブルに保存済みのレースを対象に Odds API を叩き、
exacta_odds(2連単)・win_odds(単勝)へ保存する。過去レースでも最終オッズが
取得できるため、バックフィルと差分収集が同一コードで済む(race_program.py と同型)。

scrape_log のキーは settings.BASE_URLS["race_odds_page"] の疑似URLを使う。
ただし完了扱い(200)で記録するのは statusCode=1(最終オッズ)のときだけで、
statusCode=0(中間オッズ)は記録せず次回の実行で再取得する。
"""

from __future__ import annotations

import logging

from tqdm import tqdm

from autorace_evaluator.config import settings
from autorace_evaluator.scraper.base import BaseScraper
from autorace_evaluator.storage import database, repository

logger = logging.getLogger(__name__)


def _parse_api_odds(odds_json: dict, url_meta: dict) -> dict:
    """parsers/odds_parser.py への遅延import経由の呼び出し(テストで差し替え可能)。"""
    from autorace_evaluator.parsers.odds_parser import parse_api_odds

    return parse_api_odds(odds_json, url_meta)


def scrape_odds(
    from_date: str,
    to_date: str,
    venues: list[str],
    db_path: str | None = None,
    use_cache: bool = True,
    dump_dir: str | None = None,
    progress: bool = True,
    scraper: BaseScraper | None = None,
) -> dict:
    """期間内の保存済みレースについてオッズを収集し、DBへ保存する。

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
    logger.info("オッズ収集の対象レース数: %d", len(races))

    stats = {"fetched": 0, "not_found": 0, "skipped": 0, "errors": 0,
             "rows_updated": 0}

    pbar = tqdm(desc="odds", unit="race", disable=not progress)
    try:
        for race in races:
            venue = race["venue"]
            date_str = race["race_date"]
            race_no = race["race_no"]
            url = settings.BASE_URLS["race_odds_page"].format(
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
                odds_json = scraper.post_json(
                    settings.BASE_URLS["api_odds"], payload,
                    dump_name=f"{venue}_{date_str}_{race_no}.odds",
                )
            except Exception as exc:  # noqa: BLE001 - 最終失敗を記録して継続する
                logger.warning("Fetch failed: %s (%s)", url, exc)
                repository.log_scrape(conn, url, status_code=0, error_msg=str(exc))
                stats["errors"] += 1
                continue

            if odds_json is None:
                repository.log_scrape(conn, url, status_code=404, error_msg="HTTP 404")
                stats["not_found"] += 1
                continue

            meta = {"venue": venue, "date": date_str, "race_no": race_no, "url": url}
            result = _parse_api_odds(odds_json, meta)
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
                logger.info("Odds warning %s: %s", url, w)

            status_code = result.get("status_code")
            updated_at = result.get("updated_at")
            race_id = race["race_id"]
            common = {"status_code": status_code, "updated_at": updated_at}
            n = repository.upsert_exacta_odds(
                conn, race_id, [{**r, **common} for r in result["exacta"]])
            n += repository.upsert_win_odds(
                conn, race_id, [{**r, **common} for r in result["win"]])

            stats["fetched"] += 1
            stats["rows_updated"] += n

            # 中間オッズ(statusCode=0)は完了扱いにせず、次回の実行で最終値を取り直す
            if status_code == settings.ODDS_STATUS_FINAL:
                repository.log_scrape(conn, url, status_code=200)
            else:
                logger.info("Odds: 中間オッズのため未完了 %s (statusCode=%s)",
                            url, status_code)
    finally:
        pbar.close()
        conn.close()

    return stats
