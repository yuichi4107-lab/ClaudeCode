"""scripts/autorace_weekly_update.py の純関数テスト。"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from autorace_weekly_update import compute_scrape_window  # noqa: E402


def test_normal_window_overlaps_last_collection():
    from_d, to_d = compute_scrape_window("2026-07-15", date(2026, 7, 20))
    assert from_d == "2026-07-13"  # 最終収集日-2日
    assert to_d == "2026-07-19"    # 昨日


def test_empty_db_bootstraps_one_week():
    from_d, to_d = compute_scrape_window(None, date(2026, 7, 20))
    assert to_d == "2026-07-19"
    assert from_d == "2026-07-12"


def test_window_never_inverts():
    # DBが未来日を含んでも from > to にならない
    from_d, to_d = compute_scrape_window("2026-07-25", date(2026, 7, 20))
    assert from_d <= to_d
    assert to_d == "2026-07-19"


def test_month_boundary():
    from_d, to_d = compute_scrape_window("2026-08-01", date(2026, 8, 2))
    assert from_d == "2026-07-30"
    assert to_d == "2026-08-01"
