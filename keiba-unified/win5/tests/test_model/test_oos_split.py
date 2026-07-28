import pandas as pd

from model.oos_split import time_split


def test_time_split_by_cutoff():
    df = pd.DataFrame(
        {
            "_race_date": ["2024-12-30", "2025-01-05", "2024-06-01", "2025-12-28"],
            "target": [1.0, 0.0, 1.0, 0.0],
        }
    )
    train, test = time_split(df, cutoff="2025-01-01", date_col="_race_date")
    assert sorted(train["_race_date"]) == ["2024-06-01", "2024-12-30"]
    assert sorted(test["_race_date"]) == ["2025-01-05", "2025-12-28"]


def test_time_split_empty_test_when_cutoff_future():
    df = pd.DataFrame({"_race_date": ["2024-01-01"], "target": [1.0]})
    train, test = time_split(df, cutoff="2030-01-01", date_col="_race_date")
    assert len(train) == 1
    assert len(test) == 0
