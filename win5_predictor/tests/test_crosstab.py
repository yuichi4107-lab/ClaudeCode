"""crosstab（傾向集計）のテスト。"""

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from popularity import crosstab as ct  # noqa: E402


def test_pop_bucket_boundaries():
    assert ct.pop_bucket(1) == "1-3人気"
    assert ct.pop_bucket(3) == "1-3人気"
    assert ct.pop_bucket(4) == "4-6人気"
    assert ct.pop_bucket(9) == "7-9人気"
    assert ct.pop_bucket(10) == "10人気〜"
    assert ct.pop_bucket(18) == "10人気〜"
    assert ct.pop_bucket(float("nan")) is None


def test_odds_bucket_boundaries():
    assert ct.odds_bucket(1.5) == "〜5倍"
    assert ct.odds_bucket(4.9) == "〜5倍"
    assert ct.odds_bucket(5.0) == "5-10倍"
    assert ct.odds_bucket(9.9) == "5-10倍"
    assert ct.odds_bucket(10.0) == "10-20倍"
    assert ct.odds_bucket(20.0) == "20倍〜"


def _df():
    return pd.DataFrame(
        [
            {"date": pd.Timestamp("2026-01-01"), "p1": 1, "p2": 2, "p3": 1, "p4": 5, "p5": 1},
            {"date": pd.Timestamp("2026-01-08"), "p1": 4, "p2": 1, "p3": 10, "p4": 2, "p5": 3},
        ]
    )


def test_position_by_popbucket_counts():
    cttab = ct.position_by_popbucket(_df())
    assert list(cttab.columns) == ct.POP_BUCKETS
    assert list(cttab.index) == ["1R目", "2R目", "3R目", "4R目", "5R目"]
    # 3R目: 1番人気 と 10番人気 → 1-3人気=1, 10人気〜=1
    assert cttab.loc["3R目", "1-3人気"] == 1
    assert cttab.loc["3R目", "10人気〜"] == 1


def test_position_by_popbucket_normalize_rows_sum_100():
    pct = ct.position_by_popbucket(_df(), normalize=True)
    for _, row in pct.iterrows():
        assert row.sum() == pytest.approx(100.0)


def test_position_summary_fav_rate():
    ps = ct.position_summary(_df()).set_index("レース順")
    # 2R目: 人気 2,1 → 両方1-3人気 → 100%
    assert ps.loc["2R目", "1-3人気%"] == pytest.approx(100.0)


def test_favorites_per_week():
    fpw = ct.favorites_per_week(_df(), thresh=3)
    # 1週目: 1,2,1,5,1 → 3番人気以内4頭。2週目: 4,1,10,2,3 → 3頭
    assert fpw.get("4頭") == 1
    assert fpw.get("3頭") == 1


def test_odds_crosstab_none_without_odds():
    assert ct.odds_by_pop_crosstab(_df()) is None


def test_odds_crosstab_with_odds():
    df = _df()
    for i, c in enumerate(ct.ODDS_COLS, start=1):
        df[c] = [2.0, 12.0]  # 各回の当該レース当選馬オッズ
    om = ct.odds_by_pop_crosstab(df)
    assert om is not None
    assert list(om.index) == ct.ODDS_BUCKETS
    assert om.values.sum() == 10  # 2回 × 5レース
