"""レース開催探索(URL列挙)。

現状は probe 方式のみを実装する。期間内の全日付 × 全会場 × レース番号
1..settings.MAX_RACE_NO の組み合わせで race_result URL を機械的に列挙し、
実際に取得(404判定)するかどうかは呼び出し側(scraper/race_result.py)に委ねる。

TODO(将来拡張): settings.BASE_URLS["race_info_top"] / "recent" のカレンダー
ページを解析し、開催日・開催会場を事前に絞り込むことで無駄な probe を
減らす。現状は未実装(HTML構造が確認できていないため)。probe 方式が
既定であり、当面はこれで十分。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from typing import Iterator

from autorace_evaluator.config import settings
from autorace_evaluator.storage import repository


def _date_range(from_date: str, to_date: str) -> Iterator[str]:
    """'YYYY-MM-DD' の開始日から終了日まで(両端含む)を日単位でyieldする。"""
    start = datetime.strptime(from_date, "%Y-%m-%d")
    end = datetime.strptime(to_date, "%Y-%m-%d")
    if end < start:
        return
    d = start
    while d <= end:
        yield d.strftime("%Y-%m-%d")
        d += timedelta(days=1)


def _is_404(conn: sqlite3.Connection, url: str) -> bool:
    row = conn.execute(
        "SELECT status_code FROM scrape_log WHERE url = ?", (url,)
    ).fetchone()
    return row is not None and row["status_code"] == 404


def iter_race_urls(
    from_date: str,
    to_date: str,
    venues: list[str],
    conn: sqlite3.Connection | None = None,
    stats: dict | None = None,
    probe: bool = True,
) -> Iterator[tuple[str, dict]]:
    """期間内の (race_result URL, url_meta) を probe 方式で列挙する。

    - 日付は from_date/to_date(共に 'YYYY-MM-DD')の範囲を両端含めて走査する。
    - venues 内の各会場について race_no を 1..settings.MAX_RACE_NO まで試す。
    - conn が与えられ、そのURLが repository.was_scraped(conn, url) で
      True(scrape_log に 200 or 404 の記録あり)の場合はyieldせずスキップする。
      stats が与えられていれば stats["skipped"] をインクリメントする。
      さらに race_no==1 のURLがキャッシュ上 404 だったと分かる場合は、
      その日その会場の開催なしとみなし race_no 2 以降は probe 自体しない
      (probe=True の場合のみ。過去実行分にも最適化を効かせるための処置)。
    - 呼び出し側は yield された (url, meta) を処理した後、
      generator.send(skip_rest) で次を取得できる。skip_rest に真値を
      送ると、その日その会場の残りの race_no は probe せず次の会場/日付に
      進む(典型的には race_no==1 が実際に404だった場合に使う)。
      probe=False の場合はこの送信値を無視し、全 race_no を必ず試す
      (CLI の --no-probe に対応)。

    url_meta は {"venue", "date", "race_no", "url"} を持つ dict。
    """
    for date_str in _date_range(from_date, to_date):
        for venue in venues:
            skip_venue = False
            for race_no in range(1, settings.MAX_RACE_NO + 1):
                if skip_venue:
                    break

                url = settings.BASE_URLS["race_result"].format(
                    venue=venue, date=date_str, race_no=race_no
                )

                if conn is not None and repository.was_scraped(conn, url):
                    if stats is not None:
                        stats["skipped"] = stats.get("skipped", 0) + 1
                    if probe and race_no == 1 and _is_404(conn, url):
                        skip_venue = True
                    continue

                meta = {
                    "venue": venue,
                    "date": date_str,
                    "race_no": race_no,
                    "url": url,
                }
                sent = yield url, meta
                if probe and sent:
                    skip_venue = True
