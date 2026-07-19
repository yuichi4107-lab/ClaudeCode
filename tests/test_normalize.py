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
        (3.31, 3.31),
        (3, 3.0),
        ("−", None),
        ("", None),
        (None, None),
        ("-", None),
    ],
)
def test_parse_float(raw, expected):
    assert normalize.parse_float(raw) == expected


# ------------------------------------------------------------------ parse_int

@pytest.mark.parametrize(
    "raw, expected",
    [
        ("0m", 0),
        ("10ｍ", 10),
        ("0", 0),
        (10, 10),
        (10.0, 10),
        ("3110", 3110),
        (None, None),
        ("", None),
        ("-", None),
        (True, None),
    ],
)
def test_parse_int(raw, expected):
    assert normalize.parse_int(raw) == expected


# ------------------------------------------------- track_status_from_code

@pytest.mark.parametrize(
    "code, expected",
    [
        (0, "良走路"),
        (1, "湿走路"),
        (2, "風"),
        (3, "オイル"),
        (4, "荒"),
        (5, "湿走路"),  # 斑走路は保守的に湿扱い
        ("0", "良走路"),
        (None, None),
        (99, None),
    ],
)
def test_track_status_from_code(code, expected):
    assert normalize.track_status_from_code(code) == expected


# ---------------------------------------------------------- finish_from_api

@pytest.mark.parametrize(
    "order, accident, expected",
    [
        (1, None, (1, "finished", None)),
        (8, None, (8, "finished", None)),
        ("3", None, (3, "finished", None)),
        # 着順があれば事故名が付いても完走扱い(故障完走)で備考に残す
        (4, "故障完走", (4, "finished", "故障完走")),
        (None, "落車", (None, "accident", "落車")),
        (None, "転倒", (None, "accident", "転倒")),
        (None, "欠車", (None, "scratched", "欠車")),
        (None, "除外", (None, "scratched", "除外")),
        (None, "反則妨害", (None, "violation", "反則妨害")),
        (None, "失格", (None, "violation", "失格")),
        (None, "他落", (None, "accident", "他落")),  # 「落」が先に一致
        (None, "停止", (None, "dnf", "停止")),
        (None, "故障", (None, "dnf", "故障")),
        (9, "失格", (None, "violation", "失格")),  # order>8 は着外表示
        (None, None, (None, "dnf", None)),
        (None, "???", (None, "dnf", "???")),
    ],
)
def test_finish_from_api(order, accident, expected):
    assert normalize.finish_from_api(order, accident) == expected


# -------------------------------------------------------------- st_from_api

@pytest.mark.parametrize(
    "st, foul, expected",
    [
        ("0.12", None, (0.12, 0)),
        ("0.05", "F", (0.05, 1)),
        (None, "F", (None, 1)),
        ("0.30", "L", (0.30, 0)),
        (None, None, (None, 0)),
        ("", None, (None, 0)),
    ],
)
def test_st_from_api(st, foul, expected):
    assert normalize.st_from_api(st, foul) == expected


# ----------------------------------------------------------- trial_from_api

@pytest.mark.parametrize(
    "trial, retry, expected",
    [
        ("3.31", None, (3.31, 0)),
        ("3.32", 1, (3.32, 1)),
        ("3.40", 0, (3.40, 0)),
        (None, None, (None, 0)),
        ("", 1, (None, 1)),
    ],
)
def test_trial_from_api(trial, retry, expected):
    assert normalize.trial_from_api(trial, retry) == expected


# ---------------------------------------------------------------- foul_note

@pytest.mark.parametrize(
    "code, expected",
    [
        ("F", "フライング"),
        ("L", "出残り"),
        ("B", "後方スタート"),
        ("W", "スタート戒告"),
        ("A", "その他異常発走"),
        ("X", "X"),  # 未知コードは原文
        (None, None),
        ("", None),
    ],
)
def test_foul_note(code, expected):
    assert normalize.foul_note(code) == expected
