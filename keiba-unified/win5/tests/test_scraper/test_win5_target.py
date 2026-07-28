"""WIN5スクレイパーのオフラインTDDテスト"""

import re
from datetime import date
from pathlib import Path

import pytest

from scraper.win5_target import parse_japanese_yen, parse_int_count, parse_win5_page

FIXTURES = Path(__file__).parent.parent / "fixtures"


# ─────────────────────────────────────────────────────────────
# parse_japanese_yen 単体テスト
# ─────────────────────────────────────────────────────────────

class TestParseJapaneseYen:
    def test_man_only(self):
        assert parse_japanese_yen("188万5200円") == 1_885_200

    def test_oku_and_man(self):
        assert parse_japanese_yen("7億9447万8300円") == 794_478_300

    def test_oku_only(self):
        assert parse_japanese_yen("2億円") == 200_000_000

    def test_small_amount(self):
        assert parse_japanese_yen("5200円") == 5_200

    def test_man_no_end(self):
        assert parse_japanese_yen("188万") == 1_880_000

    def test_with_comma(self):
        # カンマ入りは先に除去される
        assert parse_japanese_yen("1,885,200円") == 1_885_200

    def test_empty_string(self):
        assert parse_japanese_yen("") is None

    def test_none_equivalent(self):
        assert parse_japanese_yen("  ") is None

    def test_3oku_with_man(self):
        assert parse_japanese_yen("3億6641万9690円") == 366_419_690

    def test_carryover_amount(self):
        assert parse_japanese_yen("5億2345万6700円") == 523_456_700


# ─────────────────────────────────────────────────────────────
# parse_int_count 単体テスト
# ─────────────────────────────────────────────────────────────

class TestParseIntCount:
    def test_simple(self):
        assert parse_int_count("295票") == 295

    def test_large_with_comma(self):
        assert parse_int_count("7,944,783票") == 7_944_783

    def test_single_digit(self):
        assert parse_int_count("1票") == 1

    def test_empty_string(self):
        assert parse_int_count("") is None

    def test_no_unit(self):
        # 「票」がない場合もパース試みる
        assert parse_int_count("12345") == 12345

    def test_large_with_spaces(self):
        assert parse_int_count(" 17,842票 ") == 17_842


# ─────────────────────────────────────────────────────────────
# parse_win5_page: 的中週フィクスチャ
# ─────────────────────────────────────────────────────────────

class TestParseWin5PageHit:
    @pytest.fixture
    def html(self):
        path = FIXTURES / "win5_hit_20210207.html"
        if not path.exists():
            pytest.skip(f"Fixture not found: {path}")
        raw = path.read_bytes()
        return raw.decode("euc-jp")

    def test_returns_event(self, html):
        ev = parse_win5_page(html, date(2021, 2, 7))
        assert ev is not None

    def test_five_race_ids(self, html):
        ev = parse_win5_page(html, date(2021, 2, 7))
        ids = [ev.race1_id, ev.race2_id, ev.race3_id, ev.race4_id, ev.race5_id]
        for rid in ids:
            assert re.fullmatch(r"\d{12}", rid), f"Invalid race_id: {rid}"

    def test_payout(self, html):
        ev = parse_win5_page(html, date(2021, 2, 7))
        assert ev.payout == 1_885_200.0

    def test_num_winners(self, html):
        ev = parse_win5_page(html, date(2021, 2, 7))
        assert ev.num_winners == 295

    def test_carryover_is_none(self, html):
        ev = parse_win5_page(html, date(2021, 2, 7))
        assert ev.carryover is None

    def test_event_date(self, html):
        ev = parse_win5_page(html, date(2021, 2, 7))
        assert ev.event_date == date(2021, 2, 7)

    def test_event_id(self, html):
        ev = parse_win5_page(html, date(2021, 2, 7))
        assert ev.event_id == "20210207"

    def test_total_sales(self, html):
        ev = parse_win5_page(html, date(2021, 2, 7))
        # 7億9447万8300円 = 794_478_300
        assert ev.total_sales == 794_478_300.0


# ─────────────────────────────────────────────────────────────
# parse_win5_page: キャリーオーバー週フィクスチャ (実データ: 2026-02-01)
# ─────────────────────────────────────────────────────────────

class TestParseWin5PageCarryover:
    """2026-02-01 は払戻金=-円・的中0票・キャリーオーバー蓄積週（実データフィクスチャ）"""

    @pytest.fixture
    def html(self):
        # 実データフィクスチャを優先し、なければモックフィクスチャにフォールバック
        for fname, d in [
            ("win5_carryover_20260201.html", date(2026, 2, 1)),
            ("win5_carryover_20220116.html", date(2022, 1, 16)),
        ]:
            path = FIXTURES / fname
            if path.exists():
                raw = path.read_bytes()
                return raw.decode("euc-jp"), d
        pytest.skip("No carryover fixture found")

    def test_returns_event(self, html):
        html_str, d = html
        ev = parse_win5_page(html_str, d)
        assert ev is not None

    def test_five_race_ids(self, html):
        html_str, d = html
        ev = parse_win5_page(html_str, d)
        ids = [ev.race1_id, ev.race2_id, ev.race3_id, ev.race4_id, ev.race5_id]
        for rid in ids:
            assert re.fullmatch(r"\d{12}", rid), f"Invalid race_id: {rid}"

    def test_carryover_is_not_none(self, html):
        html_str, d = html
        ev = parse_win5_page(html_str, d)
        assert ev.carryover is not None

    def test_payout_is_none(self, html):
        html_str, d = html
        ev = parse_win5_page(html_str, d)
        # CO週（的中なし）は payout=None
        assert ev.payout is None

    def test_carryover_value(self, html):
        html_str, d = html
        ev = parse_win5_page(html_str, d)
        # 2026-02-01: 5億3990万5240円 = 539_905_240
        # モック: 3億6641万9690円 = 366_419_690
        assert ev.carryover > 0

    def test_num_winners_zero_or_small(self, html):
        html_str, d = html
        ev = parse_win5_page(html_str, d)
        # CO週は的中0または的中者が少ない
        assert ev.num_winners == 0 or ev.num_winners is None


# ─────────────────────────────────────────────────────────────
# 5レース未満の場合
# ─────────────────────────────────────────────────────────────

class TestParseWin5PageInvalid:
    def test_returns_none_when_less_than_5_races(self):
        html = """
        <html><body>
        <a href="/race/result.html?race_id=202101010101">R1</a>
        <a href="/race/result.html?race_id=202101010102">R2</a>
        </body></html>
        """
        ev = parse_win5_page(html, date(2021, 1, 1))
        assert ev is None

    def test_returns_none_when_no_races(self):
        html = "<html><body><p>No races today</p></body></html>"
        ev = parse_win5_page(html, date(2021, 1, 1))
        assert ev is None
