"""レース結果の収集(スクレイプ)処理。

autorace_evaluator.parsers.result_parser.parse_race_result(html, url_meta) -> dict
を呼び出す設計だが、result_parser.py は別途実装中でこのモジュールの
import 時点ではまだ存在しない可能性がある。そのため参照は必ず
_parse_race_result() 内の関数内 import(遅延import)で行い、本モジュール
自体は result_parser.py 抜きでも import・テストできるようにしてある。

parse_race_result が返す dict の想定契約(result_parser.py 側の実装指針):
    {
        "race": {"race_id": ..., "venue": ..., "race_date": ..., "race_no": ..., ...},
        "entries": [{"car_no": 1, "player_no": 123, "player_name": "...", ...}, ...],
        "payouts": [{"bet_type": "...", "combination": "...", "payout": ...}, ...],
    }
    パース失敗時は {"error": "message"} を返す(この場合 race/entries は無視する)。
"""

from __future__ import annotations

import logging

from tqdm import tqdm

from autorace_evaluator.scraper.base import BaseScraper
from autorace_evaluator.scraper.race_list import iter_race_urls
from autorace_evaluator.storage import database, repository

logger = logging.getLogger(__name__)


def _parse_race_result(html: str, url_meta: dict) -> dict:
    """parsers/result_parser.py への遅延import経由の呼び出し。

    result_parser.py がまだ存在しない環境でも race_result.py 自体の
    import・単体テストが壊れないよう、参照はこの関数の呼び出し時点まで
    先送りする。テストではこの関数自体を monkeypatch してスタブに
    差し替えること。
    """
    from autorace_evaluator.parsers.result_parser import parse_race_result

    return parse_race_result(html, url_meta)


def scrape_races(
    from_date: str,
    to_date: str,
    venues: list[str],
    db_path: str | None = None,
    use_cache: bool = True,
    dump_dir: str | None = None,
    progress: bool = True,
    probe: bool = True,
) -> dict:
    """期間内の南関東…ではなくオートレース5場のレース結果を収集しDBへ保存する。

    戻り値は統計 dict: {"fetched": n, "not_found": n, "skipped": n, "errors": n}
    - fetched: パース成功しDBへupsertした件数
    - not_found: 404(未開催・未確定)だった件数
    - skipped: conn の scrape_log に既に記録済みで取得しなかった件数
    - errors: HTTP取得エラー(リトライ後も失敗)またはパースエラーの件数
    """
    conn = database.get_connection(db_path)
    database.init_db(conn)

    scraper = BaseScraper(use_cache=use_cache, dump_dir=dump_dir)

    stats = {"fetched": 0, "not_found": 0, "skipped": 0, "errors": 0}

    gen = iter_race_urls(from_date, to_date, venues, conn=conn, stats=stats, probe=probe)

    pbar = tqdm(desc="scrape", unit="race", disable=not progress)
    try:
        try:
            url, meta = next(gen)
        except StopIteration:
            url = None
            meta = None

        while url is not None:
            pbar.update(1)
            skip_rest = False

            dump_name = None
            if dump_dir:
                dump_name = f"{meta['venue']}_{meta['date']}_{meta['race_no']}"

            try:
                html = scraper.get(url, dump_name=dump_name)
            except Exception as exc:  # noqa: BLE001 - リトライ後の最終失敗を記録して継続する
                logger.warning("Fetch failed: %s (%s)", url, exc)
                repository.log_scrape(conn, url, status_code=0, error_msg=str(exc))
                stats["errors"] += 1
            else:
                if html is None:
                    repository.log_scrape(conn, url, status_code=404)
                    stats["not_found"] += 1
                    if meta["race_no"] == 1:
                        skip_rest = True
                else:
                    result = _parse_race_result(html, meta)
                    error = result.get("error")
                    if error:
                        logger.warning("Parse failed: %s (%s)", url, error)
                        repository.log_scrape(conn, url, status_code=0, error_msg=str(error))
                        stats["errors"] += 1
                    else:
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

            try:
                url, meta = gen.send(skip_rest)
            except StopIteration:
                url = None
                meta = None
    finally:
        pbar.close()
        conn.close()

    return stats
