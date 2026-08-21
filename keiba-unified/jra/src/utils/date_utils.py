"""日付ユーティリティモジュール"""

from datetime import datetime, timedelta
from typing import List, Tuple


def parse_date(date_str: str) -> datetime:
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y年%m月%d日"):
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse date: {date_str}")


def date_range_months(
    start: str, end: str
) -> List[Tuple[int, int]]:
    """開始日から終了日までの(year, month)のリストを返す"""
    start_dt = parse_date(start)
    end_dt = parse_date(end)
    result = []
    current = start_dt.replace(day=1)
    while current <= end_dt:
        result.append((current.year, current.month))
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)
    return result


def get_year_range(years: List[int]) -> List[Tuple[str, str]]:
    """年のリストから各年の開始・終了日のペアリストを返す"""
    return [(f"{y}-01-01", f"{y}-12-31") for y in years]


def days_between(date1: str, date2: str) -> int:
    d1 = parse_date(date1)
    d2 = parse_date(date2)
    return abs((d2 - d1).days)
