"""レース開催探索(開催日・レース数の列挙)。

開催カレンダー API (GET /race_info/XML/Calendar?date=YYYY-MM) を月単位で
取得し、期間内の (venue, date, final_race_no) を列挙する。カレンダーが
最終レース番号を返さない日(直近の開催など)は final_race_no=None とし、
呼び出し側が 1..settings.MAX_RACE_NO を「データなし応答が出るまで」試す。

カレンダー取得自体に失敗した月は、全日付 × 全会場を final_race_no=None で
列挙するフォールバックに切り替える(APIの 4101 応答で自然に絞られる)。
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from autorace_evaluator.config import settings

logger = logging.getLogger(__name__)


def _date_range(from_date: str, to_date: str):
    """'YYYY-MM-DD' の開始日から終了日まで(両端含む)を日単位でyieldする。"""
    start = datetime.strptime(from_date, "%Y-%m-%d")
    end = datetime.strptime(to_date, "%Y-%m-%d")
    if end < start:
        return
    d = start
    while d <= end:
        yield d.strftime("%Y-%m-%d")
        d += timedelta(days=1)


def _month_range(from_date: str, to_date: str):
    """期間がまたぐ月 'YYYY-MM' を順にyieldする。"""
    start = date.fromisoformat(from_date).replace(day=1)
    end = date.fromisoformat(to_date).replace(day=1)
    cur = start
    while cur <= end:
        yield cur.strftime("%Y-%m")
        if cur.month == 12:
            cur = cur.replace(year=cur.year + 1, month=1)
        else:
            cur = cur.replace(month=cur.month + 1)


def _parse_final_race_no(value) -> int | None:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if 1 <= n <= settings.MAX_RACE_NO else None


def _extract_days_from_calendar(cal_json: dict, venues: list[str]) -> list[tuple]:
    """カレンダーAPI応答から (venue, date, final_race_no|None) を抽出する。"""
    days = []
    body = cal_json.get("body") if isinstance(cal_json, dict) else None
    if not isinstance(body, list):
        raise ValueError("calendar body is not a list")

    code_to_slug = {v: k for k, v in settings.PLACE_CODES.items()}
    wanted = set(venues)

    for block in body:
        if not isinstance(block, dict):
            continue
        slug = block.get("placeKey") or code_to_slug.get(block.get("placeCode"))
        # kawaguchi2 (placeCode=12) は placeKey が "kawaguchi" になるため
        # placeCode 側を優先して判定する
        if block.get("placeCode") == settings.PLACE_CODES[settings.TWICE_VENUE_SLUG]:
            slug = settings.TWICE_VENUE_SLUG
        if slug not in wanted:
            continue
        for day in block.get("calendar") or []:
            if not isinstance(day, dict):
                continue
            race = day.get("race")
            if not isinstance(race, dict) or not race:
                continue
            ds = day.get("date")
            if not ds:
                continue
            days.append((slug, ds, _parse_final_race_no(race.get("finalRaceNo"))))
    return days


def iter_meeting_days(
    from_date: str,
    to_date: str,
    venues: list[str],
    scraper,
    include_twice: bool = True,
) -> list[tuple]:
    """期間内の開催日リスト [(venue, "YYYY-MM-DD", final_race_no|None), ...] を返す。

    venue の並びは (日付, 会場) 順。カレンダーが取得・解析できない月は
    その月の全日付 × 全会場を final_race_no=None で返す(probe フォールバック)。
    """
    wanted = list(venues)
    if include_twice and settings.TWICE_VENUE_SLUG not in wanted:
        wanted.append(settings.TWICE_VENUE_SLUG)

    found: dict[tuple, int | None] = {}
    fallback_months: list[str] = []

    for month in _month_range(from_date, to_date):
        try:
            cal = scraper.get_json(
                settings.BASE_URLS["api_calendar"], params={"date": month}
            )
            if cal is None:
                raise ValueError("calendar API returned 404")
            days = _extract_days_from_calendar(cal, wanted)
        except Exception as exc:  # noqa: BLE001 - フォールバックに切替して続行
            logger.warning("Calendar %s の取得/解析に失敗: %s → probe方式", month, exc)
            fallback_months.append(month)
            continue
        for venue, ds, final_no in days:
            if from_date <= ds <= to_date:
                key = (venue, ds)
                # 隣接月のカレンダーに同じ日が重複して現れる。final_race_no が
                # 取れている方を優先する
                if key not in found or found[key] is None:
                    found[key] = final_no

    for month in fallback_months:
        for ds in _date_range(from_date, to_date):
            if ds[:7] != month:
                continue
            for venue in venues:  # フォールバックでは kawaguchi2 は試さない
                found.setdefault((venue, ds), None)

    return [
        (venue, ds, final_no)
        for (venue, ds), final_no in sorted(found.items(), key=lambda kv: (kv[0][1], kv[0][0]))
    ]
