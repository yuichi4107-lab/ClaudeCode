"""autorace_evaluator.parsers.normalize の単体テスト。"""

import pytest

from autorace_evaluator.parsers import normalize


# --------------------------------------------------------------- zen_to_han

@pytest.mark.parametrize(
    "raw, expected",
    [
        (None, None),
        ("", ""),
        ("３．３１", "3.31"),
        ("１０ｍ", "10m"),
        ("Ｆ", "F"),
        ("　全角空白　", "全角空白"),
        (" half width ", "halfwidth"),
        ("－", "-"),
    ],
)
def test_zen_to_han(raw, expected):
    assert normalize.zen_to_han(raw) == expected


# --------------------------------------------------------------- parse_float

@pytest.mark.parametrize(
    "raw, expected",
    [
        ("3.31", 3.31),
        ("３．３１", 3.31),
        ("−", None),
        ("", None),
        (None, None),
        ("-", None),
    ],
)
def test_parse_float(raw, expected):
    assert normalize.parse_float(raw) == expected


# ----------------------------------------------------------- parse_handicap

@pytest.mark.parametrize(
    "raw, expected",
    [
        ("0m", 0),
        ("10ｍ", 10),
        ("0", 0),
        (None, None),
        ("", None),
        ("-", None),
    ],
)
def test_parse_handicap(raw, expected):
    assert normalize.parse_handicap(raw) == expected


# --------------------------------------------------------- parse_trial_time

@pytest.mark.parametrize(
    "raw, expected",
    [
        ("3.31", (3.31, 0)),
        ("3.32再", (3.32, 1)),
        ("※3.40", (3.40, 1)),
        ("欠", (None, 0)),
        (None, (None, 0)),
        ("", (None, 0)),
    ],
)
def test_parse_trial_time(raw, expected):
    assert normalize.parse_trial_time(raw) == expected


# ----------------------------------------------------------------- parse_st

@pytest.mark.parametrize(
    "raw, expected",
    [
        ("0.12", (0.12, 0)),
        ("F", (None, 1)),
        ("Ｆ", (None, 1)),
        ("フライング", (None, 1)),
        ("-", (None, 0)),
        ("－", (None, 0)),
        ("ー", (None, 0)),
        ("欠", (None, 0)),
        ("", (None, 0)),
        (None, (None, 0)),
    ],
)
def test_parse_st(raw, expected):
    assert normalize.parse_st(raw) == expected


# ------------------------------------------------------------- parse_finish

@pytest.mark.parametrize(
    "raw, expected",
    [
        ("1", (1, "finished", None)),
        ("8", (8, "finished", None)),
        ("落", (None, "accident", "落")),
        ("妨害失格", (None, "violation", "妨害失格")),
        ("欠", (None, "scratched", "欠")),
        ("取消", (None, "scratched", "取消")),
        ("転倒", (None, "accident", "転倒")),
        (None, (None, "dnf", None)),
        ("", (None, "dnf", "")),
    ],
)
def test_parse_finish(raw, expected):
    assert normalize.parse_finish(raw) == expected


def test_parse_finish_unrecognized_text_is_dnf():
    finish_pos, status, note = normalize.parse_finish("???")
    assert finish_pos is None
    assert status == "dnf"
    assert note == "???"


# ------------------------------------------------------- parse_track_status

@pytest.mark.parametrize(
    "raw, expected",
    [
        ("良", "良走路"),
        ("良走路", "良走路"),
        ("湿走路", "湿走路"),
        ("斑走路", "湿走路"),
        ("謎走路", None),
        (None, None),
        ("", None),
    ],
)
def test_parse_track_status(raw, expected):
    assert normalize.parse_track_status(raw) == expected


# ------------------------------------------------------- parse_temperature

@pytest.mark.parametrize(
    "raw, expected",
    [
        ("32.5℃", 32.5),
        ("３２．５℃", 32.5),
        ("41.0℃", 41.0),
        (None, None),
        ("", None),
    ],
)
def test_parse_temperature(raw, expected):
    assert normalize.parse_temperature(raw) == expected
