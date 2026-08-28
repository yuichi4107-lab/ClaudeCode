"""autorace_evaluator.parsers.result_parser の単体テスト。

主対象は合成API応答(tests/fixtures/autorace/synthetic_result_api.json)。
tests/fixtures/autorace/real/ には実サイトから取得した API 応答を置いてあり、
実データが仕様通りパースできること(警告ゼロ)も検証する。
"""

import json
import re
from pathlib import Path

import pytest

from autorace_evaluator.parsers import result_parser, selectors

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "autorace"
REAL_DIR = FIXTURES_DIR / "real"

URL_META = {"venue": "kawaguchi", "date": "2026-07-18", "race_no": 3}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def synthetic_result() -> dict:
    return _load(FIXTURES_DIR / "synthetic_result_api.json")


@pytest.fixture
def synthetic_other() -> dict:
    return _load(FIXTURES_DIR / "synthetic_other_api.json")


@pytest.fixture
def parsed(synthetic_result, synthetic_other) -> dict:
    return result_parser.parse_api_race_result(
        synthetic_result, synthetic_other, URL_META)


def _entry(parsed, car_no):
    return next(e for e in parsed["entries"] if e["car_no"] == car_no)


# -------------------------------------------------------------------- race

def test_race_id_and_meta(parsed):
    assert "error" not in parsed
    race = parsed["race"]
    assert race["race_id"] == "kawaguchi_2026-07-18_3"
    assert race["venue"] == "kawaguchi"
    assert race["race_date"] == "2026-07-18"
    assert race["race_no"] == 3


def test_race_info_from_other_api(parsed):
    race = parsed["race"]
    assert race["distance"] == 3100
    assert race["weather"] == "晴"
    assert race["track_status"] == "良走路"
    assert race["trial_track_status"] == "良走路"
    assert race["temperature"] == 32.5
    assert race["track_temp"] == 36.0
    assert race["race_name"] == "テスト杯 予選"
    assert race["meeting_id"] == "kawaguchi_2026-07-16"


def test_field_size_excludes_scratched(parsed):
    # 7行中1行が欠車
    assert parsed["race"]["field_size"] == 6


def test_missing_other_api_degrades_gracefully(synthetic_result):
    result = result_parser.parse_api_race_result(synthetic_result, None, URL_META)
    assert "error" not in result
    race = result["race"]
    assert race["distance"] is None
    assert race["track_status"] is None
    assert race["meeting_id"] is None
    assert any("OtherRaceInfo" in w for w in result["warnings"])


# ----------------------------------------------------------------- entries

def test_normal_finisher(parsed):
    e = _entry(parsed, 5)
    assert e["finish_pos"] == 1
    assert e["status"] == "finished"
    assert e["player_no"] == 3110
    assert e["player_name"] == "テスト　一郎"
    assert e["handicap"] == 10
    assert e["trial_time"] == 3.31
    assert e["is_retrial"] == 0
    assert e["race_time"] == 3.365
    assert e["st"] == 0.05
    assert e["is_flying"] == 0
    assert e["violation_note"] is None


def test_retrial_flag(parsed):
    e = _entry(parsed, 1)
    assert e["trial_time"] == 3.40
    assert e["is_retrial"] == 1


def test_foul_code_recorded_as_note(parsed):
    e = _entry(parsed, 2)
    assert e["status"] == "finished"
    assert e["violation_note"] == "出残り"


def test_finished_with_trouble_keeps_order(parsed):
    # 「故障完走」は着順があるので finished、事故名は備考に残す
    e = _entry(parsed, 6)
    assert e["finish_pos"] == 4
    assert e["status"] == "finished"
    assert "故障完走" in e["violation_note"]


def test_accident_row(parsed):
    e = _entry(parsed, 3)
    assert e["finish_pos"] is None
    assert e["status"] == "accident"
    assert "落車" in e["violation_note"]


def test_scratched_row(parsed):
    e = _entry(parsed, 4)
    assert e["finish_pos"] is None
    assert e["status"] == "scratched"
    assert e["trial_time"] is None
    assert e["st"] is None


def test_violation_with_flying(parsed):
    # order=9(着外表示)+反則妨害+フライング
    e = _entry(parsed, 7)
    assert e["finish_pos"] is None
    assert e["status"] == "violation"
    assert e["is_flying"] == 1
    assert "反則妨害" in e["violation_note"]
    assert "フライング" in e["violation_note"]


def test_last_lap_time_is_always_none(parsed):
    assert all(e["last_lap_time"] is None for e in parsed["entries"])


# ----------------------------------------------------------------- payouts

def test_payouts_normal_types_only(parsed):
    payouts = parsed["payouts"]
    by_type = {}
    for p in payouts:
        by_type.setdefault(p["bet_type"], []).append(p)

    assert by_type["2連単"][0]["combination"] == "5-1"
    assert by_type["2連単"][0]["payout"] == 1520
    assert by_type["3連単"][0]["combination"] == "5-1-2"
    assert len(by_type["ワイド"]) == 2
    assert by_type["単勝"][0]["combination"] == "5"
    # 無投票(typeCode=4)・全返還(typeCode=3)は保存しない
    assert "3連複" not in by_type
    assert "複勝" not in by_type


# ---------------------------------------------------------------- failures

def _failure(code, message):
    return {"result": "Failure",
            "errors": [{"code": code, "message": message}], "body": []}


def test_failure_no_data():
    result = result_parser.parse_api_race_result(
        _failure("4101", "レスポンス件数0件"), None, URL_META)
    assert "error" in result
    assert result["error_code"] == "4101"


def test_failure_cancelled():
    result = result_parser.parse_api_race_result(
        _failure("4200", "開催中止"), None, URL_META)
    assert "error" in result
    assert result["error_code"] == "4200"


def test_empty_race_result_is_error(synthetic_other):
    empty = {"result": "Success", "errors": [], "body": {"raceResult": []}}
    result = result_parser.parse_api_race_result(empty, synthetic_other, URL_META)
    assert "error" in result


def test_non_dict_input_is_error():
    result = result_parser.parse_api_race_result("html", None, URL_META)
    assert "error" in result


# ------------------------------------------------------------ real fixtures

_REAL_STEMS = sorted(
    p.name.replace(".result.json", "")
    for p in REAL_DIR.glob("*.result.json")
)


@pytest.mark.parametrize("stem", _REAL_STEMS)
def test_real_fixtures_parse_without_warnings(stem):
    venue, date, race_no = stem.rsplit("_", 2)
    meta = {"venue": venue, "date": date, "race_no": int(race_no)}
    result_json = _load(REAL_DIR / f"{stem}.result.json")
    other_json = _load(REAL_DIR / f"{stem}.other.json")

    result = result_parser.parse_api_race_result(result_json, other_json, meta)
    assert "error" not in result
    assert result["warnings"] == []
    assert len(result["entries"]) >= 6

    # 主要フィールドが全行で取れている(完走行)
    for e in result["entries"]:
        assert e["car_no"] is not None
        assert e["player_no"] is not None
        if e["status"] == "finished":
            assert e["finish_pos"] is not None
            assert e["trial_time"] is not None
            assert e["st"] is not None
            assert e["handicap"] is not None
            assert e["race_time"] is not None


def test_real_kawaguchi_g1_values():
    """実データのスポットチェック(2026-07-17 川口1R = GIキューポラ杯)。"""
    result = result_parser.parse_api_race_result(
        _load(REAL_DIR / "kawaguchi_2026-07-17_1.result.json"),
        _load(REAL_DIR / "kawaguchi_2026-07-17_1.other.json"),
        {"venue": "kawaguchi", "date": "2026-07-17", "race_no": 1},
    )
    race = result["race"]
    assert race["distance"] == 3100
    assert race["meeting_id"] == "kawaguchi_2026-07-16"
    # situationCode=5(斑) → 湿走路(保守的), raceSituationCode=1 → 湿走路
    assert race["trial_track_status"] == "湿走路"
    assert race["track_status"] == "湿走路"

    winner = next(e for e in result["entries"] if e["finish_pos"] == 1)
    assert winner["car_no"] == 5
    assert winner["player_no"] == 3110
    assert winner["trial_time"] == 3.84
    assert winner["race_time"] == 3.852
    assert winner["st"] == 0.10
    assert winner["handicap"] == 10


def test_real_sanyou_good_track_and_payout():
    result = result_parser.parse_api_race_result(
        _load(REAL_DIR / "sanyou_2026-07-17_8.result.json"),
        _load(REAL_DIR / "sanyou_2026-07-17_8.other.json"),
        {"venue": "sanyou", "date": "2026-07-17", "race_no": 8},
    )
    assert result["race"]["track_status"] == "良走路"
    rtw = [p for p in result["payouts"] if p["bet_type"] == "2連単"]
    assert rtw and rtw[0]["combination"] == "2-6" and rtw[0]["payout"] == 2310


def test_real_html_shell_has_csrf_token_but_no_result_rows():
    """実HTMLはJS描画のシェルで、結果データを含まない代わりに
    CSRFトークン(APIのPOSTに必要)を含むことを検証する。"""
    html = (REAL_DIR / "kawaguchi_2026-07-18_1.page.html").read_text(encoding="utf-8")
    assert re.search(selectors.CSRF_TOKEN_PATTERN, html)
    # 選手行のデータテーブルは存在しない(結果はAPIから取得する設計の根拠)
    assert "raceResult" not in html
