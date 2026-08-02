"""autorace_evaluator.parsers.odds_parser の単体テスト。"""

import json
from pathlib import Path

import pytest

from autorace_evaluator.parsers import odds_parser

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "autorace"
REAL_DIR = FIXTURES_DIR / "real"

URL_META = {"venue": "sanyou", "date": "2026-07-17", "race_no": 8}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def final_odds() -> dict:
    """実応答(最終オッズ・statusCode=1)。"""
    return odds_parser.parse_api_odds(
        _load(REAL_DIR / "sanyou_2026-07-17_8.odds.json"), URL_META)


@pytest.fixture
def live_odds() -> dict:
    """実応答(中間オッズ・statusCode=0・7車)。"""
    return odds_parser.parse_api_odds(
        _load(REAL_DIR / "hamamatsu_2026-08-02_1.odds.json"),
        {"venue": "hamamatsu", "date": "2026-08-02", "race_no": 1},
    )


def _exacta(parsed, first, second):
    return next(r for r in parsed["exacta"]
                if r["first"] == first and r["second"] == second)


# ------------------------------------------------------------- 最終オッズ

def test_final_odds_status_and_update_time(final_odds):
    assert "error" not in final_odds
    assert final_odds["status_code"] == 1
    assert final_odds["updated_at"] == "2026-08-02 10:29:00"


def test_final_odds_exacta_values(final_odds):
    assert _exacta(final_odds, 2, 6)["odds"] == 23.1
    assert _exacta(final_odds, 2, 4)["odds"] == 127.3
    # 6車立て → 6×5 = 30通り(欠測なし)
    assert len(final_odds["exacta"]) == 30
    # 同じ車番の組(i-i)は含まれない
    assert all(r["first"] != r["second"] for r in final_odds["exacta"])


def test_final_odds_win_values(final_odds):
    win = {r["car_no"]: r["odds"] for r in final_odds["win"]}
    assert win[6] == 1.2
    assert win[1] == 23.7


def test_final_odds_players(final_odds):
    p = next(p for p in final_odds["players"] if p["car_no"] == 1)
    assert p["player_no"] == 1919
    assert p["trial_time"] == 3.44
    assert p["st_ave"] == 0.17
    assert p["is_absent"] == 0


# ------------------------------------------------------------- 中間オッズ

def test_live_odds_is_intermediate(live_odds):
    assert "error" not in live_odds
    assert live_odds["status_code"] == 0
    assert live_odds["updated_at"] == "2026-08-02 10:29:04"


def test_live_odds_seven_cars(live_odds):
    assert len(live_odds["players"]) == 7
    assert len(live_odds["exacta"]) == 42  # 7×6
    assert _exacta(live_odds, 1, 2)["odds"] == 34.9
    win = {r["car_no"]: r["odds"] for r in live_odds["win"]}
    assert win[4] == 3.5


def test_live_odds_trial_times(live_odds):
    trials = {p["car_no"]: p["trial_time"] for p in live_odds["players"]}
    assert trials[2] == 3.41
    assert trials[5] == 3.43


# ------------------------------------------------------------------ 防御

def test_failure_no_data():
    failure = {"result": "Failure",
               "errors": [{"code": "4101", "message": "レスポンス件数0件"}],
               "body": []}
    result = odds_parser.parse_api_odds(failure, URL_META)
    assert "error" in result
    assert result["error_code"] == "4101"


def test_failure_cancelled():
    cancelled = {"result": "Failure",
                 "errors": [{"code": "4200", "message": "開催中止"}],
                 "body": []}
    result = odds_parser.parse_api_odds(cancelled, URL_META)
    assert result["error_code"] == "4200"


def test_non_dict_input_is_error():
    assert "error" in odds_parser.parse_api_odds("<html>", URL_META)


def test_non_dict_body_is_error():
    broken = {"result": "Success", "errors": [], "body": "oops"}
    assert "error" in odds_parser.parse_api_odds(broken, URL_META)


def test_zero_and_non_numeric_odds_are_dropped():
    """"0.0"(欠車由来)・非数値・None のオッズは捨てる。"""
    body = {
        "statusCode": 1,
        "salesInfo": {"updateDate": "2026-08-02 10:29:00"},
        "playerList": [{"carNo": 1}, {"carNo": 2}, {"carNo": 3}],
        "rtwOddsList": {
            "1": {"2": "0.0", "3": "12.5"},
            "2": {"1": "-", "3": None},
            "3": {"1": "8.0", "2": ""},
        },
        "tnsOddsList": {"1": "2.0", "2": "0.0", "3": "abc"},
    }
    result = odds_parser.parse_api_odds(
        {"result": "Success", "errors": [], "body": body}, URL_META)
    assert "error" not in result
    assert sorted((r["first"], r["second"], r["odds"]) for r in result["exacta"]) == [
        (1, 3, 12.5), (3, 1, 8.0)]
    assert result["win"] == [{"car_no": 1, "odds": 2.0}]


def test_all_odds_invalid_is_error():
    body = {
        "statusCode": 0,
        "salesInfo": {"updateDate": "2026-08-02 10:29:00"},
        "playerList": [],
        "rtwOddsList": {"1": {"2": "0.0"}},
        "tnsOddsList": {"1": "0.0"},
    }
    result = odds_parser.parse_api_odds(
        {"result": "Success", "errors": [], "body": body}, URL_META)
    assert "error" in result


def test_missing_odds_lists_warn():
    body = {
        "statusCode": 1,
        "playerList": [{"carNo": 1, "trialTime": "3.40"}],
        "tnsOddsList": {"1": "2.0"},
    }
    result = odds_parser.parse_api_odds(
        {"result": "Success", "errors": [], "body": body}, URL_META)
    assert "error" not in result
    assert result["exacta"] == []
    assert result["updated_at"] is None
    assert any("rtwOddsList" in w for w in result["warnings"])
    assert any("salesInfo" in w for w in result["warnings"])


def test_broken_rows_are_skipped_with_warnings():
    body = {
        "statusCode": 1,
        "salesInfo": {"updateDate": "2026-08-02 10:29:00"},
        "playerList": [{"carNo": 1, "trialTime": "3.40"}, "ゴミ", {"noCarNo": 1}],
        "rtwOddsList": {"1": "壊れた値", "x": {"2": "5.0"}, "2": {"1": "5.0"}},
        "tnsOddsList": {"1": "2.0"},
    }
    result = odds_parser.parse_api_odds(
        {"result": "Success", "errors": [], "body": body}, URL_META)
    assert "error" not in result
    assert result["exacta"] == [{"first": 2, "second": 1, "odds": 5.0}]
    assert len(result["players"]) == 1
    assert len(result["warnings"]) >= 3
