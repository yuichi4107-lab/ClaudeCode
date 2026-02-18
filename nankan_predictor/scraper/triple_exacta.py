"""nankankeiba.com のトリプル馬単結果一覧をスクレイピングする。

対象URL例:
  https://www.nankankeiba.com/jyusyosiki_result/20260306.do?month=alltuki&jo=alljo
"""

import logging
import re
from dataclasses import dataclass, field, asdict

from bs4 import BeautifulSoup

from nankan_predictor.scraper.base import BaseScraper

logger = logging.getLogger(__name__)

BASE_URL = "https://www.nankankeiba.com/jyusyosiki_result/{date}.do"


@dataclass
class LegResult:
    """トリプル馬単の各レッグ（個別レース）の結果"""
    race_number: int = 0
    venue: str = ""
    first_horse_number: int = 0
    first_horse_name: str = ""
    first_popularity: int = 0
    second_horse_number: int = 0
    second_horse_name: str = ""
    second_popularity: int = 0
    exacta_payout: float = 0.0


@dataclass
class TripleExactaResult:
    """1開催分のトリプル馬単結果"""
    date: str = ""
    venue: str = ""
    legs: list = field(default_factory=list)  # List[LegResult]
    triple_payout: float = 0.0
    carryover: float = 0.0
    hit_count: int = 0

    def to_dict(self) -> dict:
        d = {
            "date": self.date,
            "venue": self.venue,
            "triple_payout": self.triple_payout,
            "carryover": self.carryover,
            "hit_count": self.hit_count,
        }
        for i, leg in enumerate(self.legs, 1):
            d[f"leg{i}_race_number"] = leg.race_number
            d[f"leg{i}_venue"] = leg.venue
            d[f"leg{i}_first_number"] = leg.first_horse_number
            d[f"leg{i}_first_name"] = leg.first_horse_name
            d[f"leg{i}_first_pop"] = leg.first_popularity
            d[f"leg{i}_second_number"] = leg.second_horse_number
            d[f"leg{i}_second_name"] = leg.second_horse_name
            d[f"leg{i}_second_pop"] = leg.second_popularity
            d[f"leg{i}_exacta_payout"] = leg.exacta_payout
        return d


class TripleExactaScraper(BaseScraper):
    """nankankeiba.com からトリプル馬単の結果一覧を取得する。"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # nankankeiba.com 用のヘッダー調整
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Referer": "https://www.nankankeiba.com/",
        })

    def scrape_results(
        self, year: int, month: str = "alltuki", venue: str = "alljo"
    ) -> list[TripleExactaResult]:
        """指定年の結果一覧を取得する。

        Args:
            year: 対象年 (例: 2025, 2026)
            month: 月フィルタ ("alltuki" で全月)
            venue: 会場フィルタ ("alljo" で全会場)
        """
        # URL の日付部分は任意の日付を使う (年の代表日として3月6日を使用)
        date_str = f"{year}0306"
        url = BASE_URL.format(date=date_str)
        params = {"month": month, "jo": venue}

        logger.info("Fetching triple exacta results: year=%d", year)
        try:
            html = self.get(url, params=params)
        except Exception as e:
            logger.error("Failed to fetch triple exacta results: %s", e)
            return []

        return self._parse_results(html)

    def scrape_results_raw(self, url: str, params: dict = None) -> tuple[str, list]:
        """URLを直接指定して結果を取得。デバッグ用にHTMLも返す。"""
        html = self.get(url, params=params)
        results = self._parse_results(html)
        return html, results

    def _parse_results(self, html: str) -> list[TripleExactaResult]:
        """結果一覧HTMLをパースする。"""
        soup = BeautifulSoup(html, "lxml")
        results = []

        # nankankeiba.com の結果テーブルを探索
        # 複数のパース戦略を試行
        results = self._parse_strategy_table(soup)
        if not results:
            results = self._parse_strategy_div(soup)
        if not results:
            results = self._parse_strategy_generic(soup)

        logger.info("Parsed %d triple exacta results", len(results))
        return results

    def _parse_strategy_table(self, soup: BeautifulSoup) -> list[TripleExactaResult]:
        """テーブル形式の結果をパース"""
        results = []
        # class を含むテーブルを探す
        for table in soup.select("table"):
            rows = table.select("tr")
            if len(rows) < 2:
                continue

            for row in rows[1:]:  # ヘッダー行をスキップ
                cells = row.select("td")
                result = self._try_parse_row(cells)
                if result:
                    results.append(result)

        return results

    def _parse_strategy_div(self, soup: BeautifulSoup) -> list[TripleExactaResult]:
        """div ベースのレイアウトをパース"""
        results = []
        # 結果ブロックを探索
        for block in soup.select("div.result, div.race_result, div.jyusyosiki"):
            result = self._try_parse_block(block)
            if result:
                results.append(result)
        return results

    def _parse_strategy_generic(self, soup: BeautifulSoup) -> list[TripleExactaResult]:
        """汎用パース: テキストからデータを抽出"""
        results = []
        text = soup.get_text()

        # 日付パターンでブロックを分割
        date_pattern = re.compile(
            r'(\d{4})[年/](\d{1,2})[月/](\d{1,2})[日]?\s*[（(]?[月火水木金土日]?[）)]?'
        )
        matches = list(date_pattern.finditer(text))

        for i, m in enumerate(matches):
            start = m.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            block_text = text[start:end]

            result = TripleExactaResult()
            result.date = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

            # 会場名を検出
            venue_m = re.search(r'(大井|船橋|川崎|浦和|門別)', block_text)
            if venue_m:
                result.venue = venue_m.group(1)

            # 人気を検出 (N番人気パターン)
            pop_matches = re.findall(r'(\d+)\s*番?人気', block_text)

            # 払戻金を検出
            payout_matches = re.findall(r'([\d,]+)\s*円', block_text)

            # 馬番を検出 (N→M パターン)
            combo_matches = re.findall(r'(\d+)\s*[→➝➡]\s*(\d+)', block_text)

            if pop_matches or combo_matches:
                legs = []
                for j in range(min(3, len(combo_matches))):
                    leg = LegResult()
                    leg.first_horse_number = int(combo_matches[j][0])
                    leg.second_horse_number = int(combo_matches[j][1])
                    if j * 2 + 1 < len(pop_matches):
                        leg.first_popularity = int(pop_matches[j * 2])
                        leg.second_popularity = int(pop_matches[j * 2 + 1])
                    legs.append(leg)
                result.legs = legs

                if payout_matches:
                    try:
                        result.triple_payout = float(
                            payout_matches[-1].replace(",", "")
                        )
                    except ValueError:
                        pass

                results.append(result)

        return results

    def _try_parse_row(self, cells) -> TripleExactaResult | None:
        """テーブル行からトリプル馬単結果をパースする。"""
        if len(cells) < 3:
            return None

        result = TripleExactaResult()
        texts = [c.get_text(strip=True) for c in cells]
        full_text = " ".join(texts)

        # 日付を検出
        date_m = re.search(r'(\d{4})[年/.-](\d{1,2})[月/.-](\d{1,2})', full_text)
        if date_m:
            result.date = (
                f"{date_m.group(1)}-{int(date_m.group(2)):02d}-"
                f"{int(date_m.group(3)):02d}"
            )
        else:
            return None

        # 会場検出
        venue_m = re.search(r'(大井|船橋|川崎|浦和|門別)', full_text)
        if venue_m:
            result.venue = venue_m.group(1)

        # 人気と馬番の組み合わせを検出
        pop_matches = re.findall(r'(\d+)\s*番?人気', full_text)
        combo_matches = re.findall(r'(\d+)\s*[→➝➡-]\s*(\d+)', full_text)

        legs = []
        for i in range(min(3, max(len(combo_matches), len(pop_matches) // 2))):
            leg = LegResult()
            if i < len(combo_matches):
                leg.first_horse_number = int(combo_matches[i][0])
                leg.second_horse_number = int(combo_matches[i][1])
            if i * 2 + 1 < len(pop_matches):
                leg.first_popularity = int(pop_matches[i * 2])
                leg.second_popularity = int(pop_matches[i * 2 + 1])
            legs.append(leg)
        result.legs = legs

        # 払戻金
        payout_matches = re.findall(r'([\d,]+)\s*円', full_text)
        if payout_matches:
            try:
                result.triple_payout = float(payout_matches[-1].replace(",", ""))
            except ValueError:
                pass

        return result if result.legs else None

    def _try_parse_block(self, block) -> TripleExactaResult | None:
        """divブロックからパース"""
        text = block.get_text(strip=True)
        cells = block.select("td, span, div")
        return self._try_parse_row(cells) if cells else None
