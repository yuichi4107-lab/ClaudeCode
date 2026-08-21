from datetime import date

from database.models import Win5Event
from etl.event_crosscheck import crosscheck_payouts


def test_crosscheck_detects_mismatch():
    events = [
        Win5Event(event_id="20260104", event_date=date(2026, 1, 4), payout=2775800.0),
        Win5Event(event_id="20260111", event_date=date(2026, 1, 11), payout=999.0),
        Win5Event(event_id="20260118", event_date=date(2026, 1, 18), payout=None),
    ]
    csv_rows = [
        {"date": date(2026, 1, 4), "payout_yen": 2775800.0},   # 一致
        {"date": date(2026, 1, 11), "payout_yen": 5000.0},     # 不一致
        {"date": date(2026, 1, 18), "payout_yen": None},       # 両方None=一致
    ]
    mm = crosscheck_payouts(events, csv_rows)
    assert mm == [(date(2026, 1, 11), 999.0, 5000.0)]
