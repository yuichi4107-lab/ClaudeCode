"""レース結果の収集(JSON API経由)。

開催カレンダーで (会場, 日付, 最終レース番号) を列挙し、各レースについて
RaceResult / OtherRaceInfo の2つの JSON API を叩いてDBへ保存する。

scrape_log のキーには結果ページの公開URL
(https://autorace.jp/race_info/RaceResult/{venue}/{date}_{race_no})
を使う。API の「データなし(4101)」「中止(4200)」は HTTP 404 相当として
status_code=404 で記録し、再実行時にスキップする。
"""

from __future__ import annotations

import logging

from tqdm import tqdm

from autorace_evaluator.config import settings
from autorace_evaluator.scraper.base import BaseScraper
from autorace_evaluator.scraper.race_list import iter_meeting_days
from autorace_evaluator.storage import database, repository

logger = logging.getLogger(__name__)


def _parse_race_result(result_json: dict, other_json: dict | None, url_meta: dict) -> dict:
    """parsers/result_parser.py への遅延import経由の呼び出し。

    テストではこの関数自体を monkeypatch してスタブに差し替えること。
    """
    from autorace_evaluator.parsers.result_parser import parse_api_race_result

    return parse_api_race_result(result_json, other_json, url_meta)


def _page_url(venue: str, date: str, race_no: int) -> str:
    return settings.BASE_URLS["race_result_page"].format(
        venue=venue, date=date, race_no=race_no
    )


def scrape_races(
    from_date: str,
    to_date: str,
    venues: list[str],
    db_path: str | None = None,
    use_cache: bool = True,
    dump_dir: str | None = None,
    progress: bool = True,
    scraper: BaseScraper | None = None,
) -> dict:
    """期間内のオートレース5場のレース結果を収集しDBへ保存する。

    戻り値は統計 dict:
        {"fetched": n, "not_found": n, "cancelled": n, "skipped": n, "errors": n}
    - fetched: パース成功しDBへupsertした件数
    - not_found: データなし(4101)だった件数
    - cancelled: 開催中止(4200)だった件数
    - skipped: scrape_log に記録済みで取得しなかった件数
    - errors: HTTP取得エラー(リトライ後も失敗)またはパースエラーの件数
    """
    conn = database.get_connection(db_path)
    database.init_db(conn)

    if scraper is None:
        scraper = BaseScraper(use_cache=use_cache, dump_dir=dump_dir)

    stats = {"fetched": 0, "not_found": 0, "cancelled": 0, "skipped": 0, "errors": 0}

    days = iter_meeting_days(from_date, to_date, venues, scraper)
    logger.info("開催日数(会場×日付): %d", len(days))

    pbar = tqdm(desc="scrape", unit="race", disable=not progress)
    try:
        for venue, date_str, final_race_no in days:
            max_no = final_race_no or settings.MAX_RACE_NO
            probing = final_race_no is None
            for race_no in range(1, max_no + 1):
                url = _page_url(venue, date_str, race_no)

                if repository.was_scraped(conn, url):
                    stats["skipped"] += 1
                    continue

                pbar.update(1)
                stop_day = _scrape_one(
                    scraper, conn, venue, date_str, race_no, url, stats, probing
                )
                if stop_day:
                    break
    finally:
        pbar.close()
        conn.close()

    return stats


def _scrape_one(
    scraper: BaseScraper,
    conn,
    venue: str,
    date_str: str,
    race_no: int,
    url: str,
    stats: dict,
    probing: bool,
) -> bool:
    """1レース分を取得・保存する。

    戻り値 True は「この日この会場の残りレース番号は試さなくてよい」
    (最終レース番号が不明な probing 時にデータなし応答が出た場合)。
    """
    payload = {
        "placeCode": settings.PLACE_CODES[venue],
        "raceDate": date_str,
        "raceNo": race_no,
    }
    dump_base = f"{venue}_{date_str}_{race_no}"

    try:
        result_json = scraper.post_json(
            settings.BASE_URLS["api_race_result"], payload,
            dump_name=f"{dump_base}.result",
        )
    except Exception as exc:  # noqa: BLE001 - リトライ後の最終失敗を記録して継続する
        logger.warning("Fetch failed: %s (%s)", url, exc)
        repository.log_scrape(conn, url, status_code=0, error_msg=str(exc))
        stats["errors"] += 1
        return False

    if result_json is None:
        repository.log_scrape(conn, url, status_code=404, error_msg="HTTP 404")
        stats["not_found"] += 1
        return probing

    meta = {"venue": venue, "date": date_str, "race_no": race_no, "url": url}

    # Failure はパーサに判定させる(4101=データなし, 4200=中止)
    if result_json.get("result") != "Success":
        parsed = _parse_race_result(result_json, None, meta)
        code = parsed.get("error_code")
        if code == settings.API_CODE_CANCELLED:
            repository.log_scrape(conn, url, status_code=404, error_msg="中止(4200)")
            stats["cancelled"] += 1
            return False  # cancel6(途中から中止)があるため残レースは試す
        if code == settings.API_CODE_NO_DATA:
            repository.log_scrape(conn, url, status_code=404, error_msg="データなし(4101)")
            stats["not_found"] += 1
            return probing
        logger.warning("API failure: %s (%s)", url, parsed.get("error"))
        repository.log_scrape(conn, url, status_code=0, error_msg=str(parsed.get("error")))
        stats["errors"] += 1
        return False

    try:
        other_json = scraper.post_json(
            settings.BASE_URLS["api_other_race_info"], payload,
            dump_name=f"{dump_base}.other",
        )
    except Exception as exc:  # noqa: BLE001 - 補足情報の失敗は警告扱いで続行
        logger.warning("OtherRaceInfo failed: %s (%s)", url, exc)
        other_json = None

    result = _parse_race_result(result_json, other_json, meta)
    error = result.get("error")
    if error:
        logger.warning("Parse failed: %s (%s)", url, error)
        repository.log_scrape(conn, url, status_code=0, error_msg=str(error))
        stats["errors"] += 1
        return False

    for w in result.get("warnings", []):
        logger.info("Parse warning %s: %s", url, w)

    race = result["race"]
    entries = result.get("entries", [])
    payouts = result.get("payouts", [])

    repository.upsert_race(conn, race)
    # race_entries.player_no は players(player_no) への外部キー
    # (foreign_keys=ON)なので、entries より先に players を確定させる。
    for entry in entries:
        if entry.get("player_no") is not None:
            repository.upsert_player(
                conn, entry["player_no"], entry.get("player_name") or ""
            )
    repository.upsert_entries(conn, race["race_id"], entries)
    if payouts:
        repository.upsert_payouts(conn, race["race_id"], payouts)

    repository.log_scrape(conn, url, status_code=200)
    stats["fetched"] += 1
    return False
