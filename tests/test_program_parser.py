"""autorace_evaluator.parsers.program_parser の単体テスト。"""

import json
from pathlib import Path

import pytest

from autorace_evaluator.parsers import program_parser

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "autorace"
REAL_DIR = FIXTURES_DIR / "real"

URL_META = {"venue": "kawaguchi", "date": "2026-07-18", "race_no": 3}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def parsed() -> dict:
    return program_parser.parse_api_program(
        _load(FIXTURES_DIR / "synthetic_program_api.json"), URL_META)


def _entry(parsed, car_no):
    return next(e for e in parsed["entries"] if e["car_no"] == car_no)


def test_parses_all_rows(parsed):
    assert "error" not in parsed
    assert len(parsed["entries"]) == 7
    assert parsed["warnings"] == []


def test_field_normalization(parsed):
    e = _entry(parsed, 5)
    assert e["player_no"] == 3110
    assert e["bike_class"] == "1級車"
    assert e["graduation_code"] == 31
    assert e["player_rank"] == "S-10"
    assert e["age"] == 35
    assert e["rate2"] == 45.0
    assert e["rate3"] == 60.0


def test_rookie_bike_class(parsed):
    e = _entry(parsed, 3)
    assert e["bike_class"] == "2級車"
    assert e["graduation_code"] == 38


def test_null_rates(parsed):
    e = _entry(parsed, 4)
    assert e["rate2"] is None
    assert e["rate3"] is None


def test_failure_no_data():
    failure = {"result": "Failure",
               "errors": [{"code": "4101", "message": "レスポンス件数0件"}],
               "body": []}
    result = program_parser.parse_api_program(failure, URL_META)
    assert "error" in result
    assert result["error_code"] == "4101"


def test_empty_player_list_is_error():
    empty = {"result": "Success", "errors": [], "body": {"playerList": []}}
    result = program_parser.parse_api_program(empty, URL_META)
    assert "error" in result


def test_non_dict_input_is_error():
    assert "error" in program_parser.parse_api_program("html", URL_META)


def test_real_program_fixture():
    """実応答(2026-07-17 山陽1R)のスポットチェック。"""
    result = program_parser.parse_api_program(
        _load(REAL_DIR / "sanyou_2026-07-17_1.program.json"),
        {"venue": "sanyou", "date": "2026-07-17", "race_no": 1},
    )
    assert "error" not in result
    assert result["warnings"] == []
    # 38期の新人が2級車で判定される
    rookie = next(e for e in result["entries"] if e["player_no"] == 9030)
    assert rookie["bike_class"] == "2級車"
    assert rookie["graduation_code"] == 38
    assert rookie["player_rank"] == "B-114"
    veteran = next(e for e in result["entries"] if e["player_no"] == 2802)
    assert veteran["bike_class"] == "1級車"
