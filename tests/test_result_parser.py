"""autorace_evaluator.parsers.result_parser の単体テスト。

実HTMLは入手できない環境のため、tests/fixtures/autorace/synthetic_result.html
(selectors.py の想定DOMに準拠した合成データ)を主な検証対象にする。
tests/fixtures/autorace/real/ に実HTMLが置かれていれば、それも glob して
「例外なくパースできる」ことだけ追加検証する(なければ skip)。
"""

from pathlib import Path

import pytest

from autorace_evaluator.parsers import result_parser

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "autorace"
SYNTHETIC_HTML_PATH = FIXTURES_DIR / "synthetic_result.html"

URL_META = {"venue": "kawaguchi", "date": "2026-07-18", "race_no": 3}


@pytest.fixture
def synthetic_html() -> str:
    return SYNTHETIC_HTML_PATH.read_text(encoding="utf-8")


@pytest.fixture
def parsed(synthetic_html) -> dict:
    return result_parser.parse_race_result(synthetic_html, URL_META)


# -------------------------------------------------------------------- race

def test_race_id_and_meta(parsed):
    assert "error" not in parsed
    race = parsed["race"]
    assert race["race_id"] == "kawaguchi_2026-07-18_3"
    assert race["venue"] == "kawaguchi"
    assert race["race_date"] == "2026-07-18"
    assert race["race_no"] == 3


def test_race_distance_from_header(parsed):
    assert parsed["race"]["distance"] == 3100


def test_race_weather_block(parsed):
    race = parsed["race"]
    assert race["weather"] == "晴"
    assert race["track_status"] == "良走路"
    assert race["temperature"] == 32.5
    assert race["track_temp"] == 41.0


def test_field_size_excludes_only_scratched(parsed):
    # 8車すべて出走(欠車はいない)。落車・失格も出走扱いで数える。
    assert parsed["race"]["field_size"] == 8


# ----------------------------------------------------------------- entries

def test_entry_count(parsed):
    assert len(parsed["entries"]) == 8


def _entry(parsed, car_no):
    return next(e for e in parsed["entries"] if e["car_no"] == car_no)


def test_normal_finisher(parsed):
    e = _entry(parsed, 1)
    assert e["finish_pos"] == 1
    assert e["status"] == "finished"
    assert e["handicap"] == 0
    assert e["trial_time"] == 3.31
    assert e["is_retrial"] == 0
    assert e["st"] == 0.05
    assert e["is_flying"] == 0
    assert e["violation_note"] is None


def test_retrial_mark(parsed):
    e = _entry(parsed, 2)
    assert e["trial_time"] == 3.32
    assert e["is_retrial"] == 1
    assert e["handicap"] == 10


def test_flying_start(parsed):
    e = _entry(parsed, 3)
    assert e["st"] is None
    assert e["is_flying"] == 1


def test_accident_car(parsed):
    e = _entry(parsed, 4)
    assert e["finish_pos"] is None
    assert e["status"] == "accident"
    assert e["violation_note"] == "落"


def test_violation_car(parsed):
    e = _entry(parsed, 5)
    assert e["finish_pos"] is None
    assert e["status"] == "violation"
    assert e["violation_note"] == "妨害失格"


def test_player_no_extracted_from_href(parsed):
    e = _entry(parsed, 1)
    assert e["player_no"] == 12345
    assert e["player_name"] == "田中 一郎"


def test_all_player_no_resolved(parsed):
    for e in parsed["entries"]:
        assert e["player_no"] is not None


# ----------------------------------------------------------------- payouts

def test_payouts(parsed):
    payouts = parsed["payouts"]
    assert len(payouts) == 2
    trifecta = next(p for p in payouts if p["bet_type"] == "3連単")
    assert trifecta["combination"] == "1-2-3"
    assert trifecta["payout"] == 12340.0

    trio = next(p for p in payouts if p["bet_type"] == "3連複")
    assert trio["combination"] == "1-2-3"
    assert trio["payout"] == 3210.0


# ------------------------------------------------------------------ errors

def test_missing_result_table_returns_error():
    html = "<html><body><p>結果テーブルはありません</p></body></html>"
    result = result_parser.parse_race_result(html, URL_META)
    assert "error" in result
    assert result["warnings"]


def test_unresolvable_headers_warns_and_continues(synthetic_html):
    # 見出しの一部を HEADER_FIELD_MAP のどの同義語にもマッチしない文字列に差し替える。
    mangled = synthetic_html.replace("<th>ハンデ</th>", "<th>謎ラベル</th>")
    assert mangled != synthetic_html  # 置換が実際に行われたことを確認

    result = result_parser.parse_race_result(mangled, URL_META)

    assert "error" not in result
    assert any("見出し不明" in w for w in result["warnings"])
    # car_no は解決できているので通常どおりパースは継続する
    assert len(result["entries"]) == 8
    # ハンデ列が解決できなくなった分、handicap は None になる
    assert all(e["handicap"] is None for e in result["entries"])


# --------------------------------------------------------- real fixtures

REAL_FIXTURES_DIR = FIXTURES_DIR / "real"


def _real_fixture_paths():
    if not REAL_FIXTURES_DIR.exists():
        return []
    return sorted(REAL_FIXTURES_DIR.glob("*.html"))


@pytest.mark.parametrize("html_path", _real_fixture_paths(), ids=lambda p: p.name)
def test_real_fixtures_parse_without_error(html_path):
    html = html_path.read_text(encoding="utf-8")
    # ファイル名 {venue}_{YYYY-MM-DD}_{race_no}.html からメタ情報を推定する
    import re

    m = re.search(
        r"(kawaguchi|isesaki|hamamatsu|sanyou|iizuka)_(\d{4}-\d{2}-\d{2})_(\d+)",
        html_path.stem,
    )
    if m:
        venue, date, race_no = m.groups()
        url_meta = {"venue": venue, "date": date, "race_no": int(race_no)}
    else:
        url_meta = {"venue": "unknown", "date": "1970-01-01", "race_no": 0}

    result = result_parser.parse_race_result(html, url_meta)
    assert "error" not in result, result.get("error")


def test_real_fixtures_skip_if_none_present():
    if _real_fixture_paths():
        pytest.skip("real fixtures present; covered by test_real_fixtures_parse_without_error")
    pytest.skip("tests/fixtures/autorace/real/ に実HTMLが無いためスキップ")
