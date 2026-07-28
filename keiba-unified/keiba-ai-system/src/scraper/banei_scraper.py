"""帯広ばんえい競馬のレース結果データスクレイパー

地方競馬の公式サイト (keiba.go.jp) からレース結果データを取得する。

URL構造:
  - レース一覧: /KeibaWeb/TodayRaceInfo/RaceList?k_raceDate=YYYY/MM/DD&k_babaCode=36
  - 出馬表:     /KeibaWeb/TodayRaceInfo/DebaTable?k_raceDate=YYYY/MM/DD&k_raceNo=N&k_babaCode=36
  - 成績:       /KeibaWeb/TodayRaceInfo/RaceMarkTable?k_raceDate=YYYY/MM/DD&k_raceNo=N&k_babaCode=36
"""

from __future__ import annotations

import logging
import re
import time
from datetime import date, timedelta
from io import StringIO

import pandas as pd
import requests
from bs4 import BeautifulSoup

from config.settings import (
    OBIHIRO_COURSE_CODE,
    RAW_DATA_DIR,
    REQUEST_INTERVAL,
    USER_AGENT,
)

logger = logging.getLogger(__name__)

BASE = "https://www.keiba.go.jp/KeibaWeb/TodayRaceInfo"


class BaneiScraper:
    """帯広ばんえい競馬データスクレイパー"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)

    def _get(self, url: str, params: dict | None = None) -> BeautifulSoup | None:
        """GETリクエストを送信してBeautifulSoupオブジェクトを返す"""
        try:
            resp = self.session.get(url, params=params, timeout=30)
            resp.raise_for_status()
            resp.encoding = resp.apparent_encoding
            time.sleep(REQUEST_INTERVAL)
            return BeautifulSoup(resp.text, "lxml")
        except requests.RequestException as e:
            logger.error("リクエスト失敗: %s - %s", url, e)
            return None

    def _get_html(self, url: str, params: dict | None = None) -> str | None:
        """GETリクエストを送信してHTML文字列を返す（pandas.read_html用）"""
        try:
            resp = self.session.get(url, params=params, timeout=30)
            resp.raise_for_status()
            resp.encoding = resp.apparent_encoding
            time.sleep(REQUEST_INTERVAL)
            return resp.text
        except requests.RequestException as e:
            logger.error("リクエスト失敗: %s - %s", url, e)
            return None

    def get_race_list(self, race_date: date) -> list[dict]:
        """指定日のレース一覧を取得する"""
        date_str = race_date.strftime("%Y/%m/%d")
        params = {"k_raceDate": date_str, "k_babaCode": OBIHIRO_COURSE_CODE}
        soup = self._get(f"{BASE}/RaceList", params=params)
        if soup is None:
            return []

        races = []
        # レース一覧ページからリンクを抽出
        for link in soup.find_all("a", href=True):
            href = link["href"]
            if "RaceMarkTable" in href or "DebaTable" in href:
                # レース番号をURLパラメータから抽出
                race_no_match = re.search(r"k_raceNo=(\d+)", href)
                if race_no_match:
                    race_no = race_no_match.group(1)
                    # 重複チェック
                    if not any(r["race_no"] == race_no for r in races):
                        races.append(
                            {
                                "date": date_str,
                                "race_no": race_no,
                            }
                        )

        logger.info("%s: %d レース取得", date_str, len(races))
        return races

    def get_race_result(self, race_date: date, race_no: str) -> list[dict]:
        """レース結果の詳細を取得する

        pandas.read_html でテーブルを取得し、
        BeautifulSoupで補足情報（レース名等）を取得する。
        """
        date_str = race_date.strftime("%Y/%m/%d")
        params = {
            "k_raceDate": date_str,
            "k_raceNo": race_no,
            "k_babaCode": OBIHIRO_COURSE_CODE,
        }

        # HTML取得
        html = self._get_html(f"{BASE}/RaceMarkTable", params=params)
        if html is None:
            return []

        soup = BeautifulSoup(html, "lxml")

        # レース情報を取得
        race_name = ""
        distance = None
        track_condition = ""

        page_text = soup.get_text()

        # レース名（「第N競走」パターンまたはレース名を取得）
        race_name_match = re.search(r"第\d+競走\s*(\S+)", page_text)
        if race_name_match:
            race_name = race_name_match.group(0)
        else:
            # 成績表の手前にあるレース名を探す
            name_match = re.search(r"([\u3040-\u9fffＡ-Ｚａ-ｚ０-９]+[杯賞特別]+)", page_text)
            if name_match:
                race_name = name_match.group(1)

        # 距離（全角・半角のm/ｍ両方に対応）
        dist_match = re.search(r"(\d{2,4})\s*[m��]", page_text)
        if dist_match:
            distance = int(dist_match.group(1))

        # ばんえい馬場状態（数値で表される: 例 2.2）
        track_match = re.search(r"開場[：:]\s*([\d.]+)", page_text)
        if track_match:
            track_condition = track_match.group(1)
        else:
            for cond in ["良", "稍重", "重", "不良"]:
                if cond in page_text:
                    track_condition = cond
                    break

        # エラーページ検出 → 成績未確定のため出馬表にフォールバック
        if 'class="errorInfo"' in html or "<title>エラー</title>" in html:
            logger.info("成績ページ未公開のため出馬表から取得: %s R%s", date_str, race_no)
            return self.get_race_entries(race_date, race_no)

        # テーブルをpandasで読み込み
        try:
            tables = pd.read_html(StringIO(html))
        except (ValueError, OSError):
            logger.info("テーブル解析失敗のため出馬表から取得: %s R%s", date_str, race_no)
            return self.get_race_entries(race_date, race_no)

        if not tables:
            return []

        # 成績テーブルを探す。公式サイトは�2026年時点で、ヘッダー行が
        # DataFrameのcolumnsに入る形式へ変わっている。
        result_table = None
        data_rows = None
        for t in tables:
            if len(t.columns) == 15 and len(t) >= 3:
                column_text = " ".join(str(v) for v in t.columns)
                if "馬番" in column_text and ("着順" in column_text or "着" in column_text):
                    result_table = t
                    data_rows = t
                    break

                # 旧形式: 2行目にヘッダーが入り、先頭2行を読み飛ばす。
                header_text = " ".join(str(v) for v in t.iloc[1].values)
                if "馬" in header_text and ("着" in header_text or "順" in header_text):
                    result_table = t
                    data_rows = t.iloc[2:]
                    break

        if result_table is None:
            # レース前: 出馬表からデータを取得
            logger.info("成績未確定のため出馬表から取得: %s R%s", date_str, race_no)
            return self.get_race_entries(race_date, race_no)

        records = []
        for _, row in data_rows.iterrows():
            record = self._parse_result_row(row, race_date, race_no, race_name, distance, track_condition)
            if record:
                records.append(record)

        return records

    def _parse_result_row(
        self,
        row: pd.Series,
        race_date: date,
        race_no: str,
        race_name: str,
        distance: int | None,
        track_condition: str,
    ) -> dict | None:
        """pandas DataFrameの行をパースしてレコードを作成"""
        values = [str(v) for v in row.values]
        text = " ".join(values)

        # 少なくとも馬名らしき日本語と数字が含まれること
        has_japanese = bool(re.search(r"[\u3040-\u9fff]{2,}", text))
        has_number = bool(re.search(r"\d", text))
        if not has_japanese or not has_number:
            return None

        record = {
            "race_date": race_date.strftime("%Y-%m-%d"),
            "race_no": race_no,
            "race_name": race_name,
            "distance": distance,
            "track_condition": track_condition,
        }

        # カラム数に応じてマッピング
        cols = list(row.index)
        vals = list(row.values)

        # 帯広ばんえい成績テーブルのカラム順（15列）:
        # 着順, 枠番, 馬番, 馬名, 所属, 性齢, 積載重量, 騎手(所属), 調教師,
        # 馬体重(増減), タイム, 着差, 上がり3F, 人気, 単勝オッズ
        field_mappings = [
            ("finish_order", self._safe_int),
            ("post_position", self._safe_int),
            ("horse_number", self._safe_int),
            ("horse_name", str),
            ("_affiliation", str),  # 所属（使わない）
            ("sex_age", str),
            ("weight_carry", self._safe_float),
            ("jockey", str),
            ("trainer", str),
            ("horse_weight", self._safe_float),
            ("time", str),
            ("_margin", str),  # 着差（使わない）
            ("_last_3f", str),  # 上り3F（使わない）
            ("popularity", self._safe_int),
            ("odds", self._safe_float),
        ]

        for i, (field_name, converter) in enumerate(field_mappings):
            if i < len(vals):
                try:
                    val = str(vals[i]).strip()
                    if val in ("nan", "None", ""):
                        record[field_name] = None
                    else:
                        record[field_name] = converter(val)
                except (ValueError, TypeError):
                    record[field_name] = None

        # 騎手名のクリーンアップ: "西謙一(ばんえい)" → "西謙一", "☆竹ケ茉(ばんえい〆" → "��ケ茉"
        jockey = record.get("jockey", "")
        if jockey and isinstance(jockey, str):
            jockey = re.sub(r"\(.*?\)", "", jockey).strip()
            jockey = re.sub(r"^[★▲△◇☆]", "", jockey).strip()
            record["jockey"] = jockey

        # 性別と年齢を分離: "牝 4" or "牡4" → sex="牝", age=4
        sex_age = record.get("sex_age", "")
        if sex_age and isinstance(sex_age, str):
            sex_age = sex_age.strip()
            if len(sex_age) >= 2:
                record["sex"] = sex_age[0]
                record["age"] = self._safe_int(re.sub(r"[^\d]", "", sex_age[1:]))

        # 不要なフェールドを除去
        for key in list(record.keys()):
            if key.startswith("_"):
                del record[key]

        return record

    @staticmethod
    def _safe_int(value) -> int | None:
        try:
            return int(str(value).replace(",", "").strip())
        except (ValueError, AttributeError, TypeError):
            return None

    @staticmethod
    def _safe_float(value) -> float | None:
        try:
            match = re.search(r"-?\d+(?:\.\d+)?", str(value).replace(",", "").strip())
            if not match:
                return None
            return float(match.group(0))
        except (ValueError, AttributeError, TypeError):
            return None

    def get_race_entries(self, race_date: date, race_no: str) -> list[dict]:
        """出馬表（DebaTable）からレース前のデータを取得する

        成績ページにデータが無い場合（レース前）に使用する。
        """
        date_str = race_date.strftime("%Y/%m/%d")
        params = {
            "k_raceDate": date_str,
            "k_raceNo": race_no,
            "k_babaCode": OBIHIRO_COURSE_CODE,
        }
        soup = self._get(f"{BASE}/DebaTable", params=params)
        if soup is None:
            return []

        page_text = soup.get_text()
        lines = [l.strip() for l in page_text.split("\n") if l.strip()]

        # 距離
        distance = None
        dist_match = re.search(r"(\d{2,4})\s*[m�]", page_text)
        if dist_match:
            distance = int(dist_match.group(1))

        # 馬場状態
        track_condition = ""
        track_match = re.search(r"馬場[：:]\s*([\d.]+)", page_text)
        if track_match:
            track_condition = track_match.group(1)

        # 馬データをテキスト解析で抽出
        records = []
        i = 0
        while i < len(lines) - 5:
            # 枠番(数字) + 馬番(数字) + 馬名(カタカナ) のパターンを探す
            if (re.match(r"^\d{1,2}$", lines[i]) and
                i + 2 < len(lines) and
                re.match(r"^\d{1,2}$", lines[i + 1]) and
                re.search(r"[\u30A0-\u30FF]{2,}", lines[i + 2])):

                post_pos = int(lines[i])
                horse_num = int(lines[i + 1])
                horse_name = lines[i + 2]

                # 既に取得済みの馬番はスキップ
                if any(r["horse_number"] == horse_num for r in records):
                    i += 1
                    continue

                # 騎手（次の「(ばんえい)」を含む行）
                jockey = ""
                odds_val = None
                for j in range(i + 3, min(i + 8, len(lines))):
                    if "ばんえい" in lines[j] and not jockey:
                        jockey = lines[j]
                        jockey = re.sub(r"[（(].*?[）)]", "", jockey).strip()
                        jockey = re.sub(r"^[★▲△◇☆]", "", jockey).strip()
                    odds_m = re.match(r"([\d.]+)\(\d+人気\)", lines[j])
                    if odds_m:
                        odds_val = float(odds_m.group(1))

                # 性齢（「牡N」「牝N」「セN」「セン N」パターン）
                sex_age = ""
                horse_weight = None
                trainer = ""
                past_weight = None  # 過去戦績からの馬体量（フォールバック用）
                for j in range(i + 5, min(i + 60, len(lines))):
                    sa_m = re.match(r"^(セン|[牡牝セ])\s*(\d{1,2})$", lines[j])
                    if sa_m and not sex_age:
                        sex_age = sa_m.group(1)[0] + sa_m.group(2)
                    # 当日馬体重（「1006(+1)」形式）
                    wt_m = re.match(r"^(\d{3,4})\s*\([+-]?\d+\)$", lines[j])
                    if wt_m and horse_weight is None:
                        horse_weight = float(wt_m.group(1))
                    # 過去戦績行（「N人 NNNN 騎手名 NNN」形式）から馬体重を取得
                    past_m = re.match(r"\d+人\s+(\d{3,4})\s+\S+\s+\d{3,4}", lines[j])
                    if past_m and past_weight is None:
                        past_weight = float(past_m.group(1))
                    # 調教師
                    if "ばんえい" in lines[j] and jockey and lines[j] != jockey + "（ばんえい）":
                        candidate = re.sub(r"[（(].*?[）)]", "", lines[j]).strip()
                        if candidate != jockey and not trainer:
                            trainer = candidate

                # 当日馬体量がなければ直近の過去体量を使用
                if horse_weight is None and past_weight is not None:
                    horse_weight = past_weight

                # 積載重量: 過去戦績行 "N人 NNNN 騎手名 NNN" から取得
                weight_carry = None
                for j in range(i + 5, min(i + 60, len(lines))):
                    wc_m = re.match(r"\d+人\s+\d{3,4}\s+\S+\s+(\d{3,4})", lines[j])
                    if wc_m and weight_carry is None:
                        weight_carry = float(wc_m.group(1))

                record = {
                    "race_date": race_date.strftime("%Y-%m-%d"),
                    "race_no": race_no,
                    "race_name": "",
                    "distance": distance,
                    "track_condition": track_condition,
                    "finish_order": None,
                    "post_position": post_pos,
                    "horse_number": horse_num,
                    "horse_name": horse_name,
                    "sex_age": sex_age,
                    "weight_carry": weight_carry,
                    "jockey": jockey,
                    "trainer": trainer,
                    "horse_weight": horse_weight,
                    "time": None,
                    "popularity": None,
                    "sex": sex_age[0] if sex_age else None,
                    "age": self._safe_int(sex_age[1:]) if sex_age else None,
                    "odds": odds_val,
                }
                records.append(record)

            i += 1

        logger.info("出馬表から %d 頭取得: %s R%s", len(records), date_str, race_no)
        return records

    def get_odds(self, race_date: date, race_no: str) -> dict[str, float]:
        """出馬表ページから単勝オッズを取得する

        Returns:
            {馬番(str): オッズ(float)} の辞書
        """
        date_str = race_date.strftime("%Y/%m/%d")
        params = {
            "k_raceDate": date_str,
            "k_raceNo": race_no,
            "k_babaCode": OBIHIRO_COURSE_CODE,
        }
        soup = self._get(f"{BASE}/DebaTable", params=params)
        if soup is None:
            return {}

        odds_dict = {}
        page_text = soup.get_text()

        # ページ全体から「馬番 ... オッズ(N人気)」パターンを探す
        # 出馬表では各馬のブロックに馬番とオッズが含まれる
        current_num = None
        for line in page_text.split("\n"):
            line = line.strip()
            if not line:
                continue

            # 馬番の検出（単独の1〜2桁数字）
            num_match = re.match(r"^(\d{1,2})$", line)
            if num_match:
                candidate = num_match.group(1)
                if 1 <= int(candidate) <= 20:
                    current_num = candidate

            # オッズの検出
            odds_match = re.search(r"([\d.]+)\s*\(\d+人気\)", line)
            if odds_match and current_num and current_num not in odds_dict:
                odds_dict[current_num] = float(odds_match.group(1))
                current_num = None

        return odds_dict

    def scrape_date_range(
        self, start_date: date, end_date: date, *, use_entries: bool = False
    ) -> pd.DataFrame:
        """指定期間のレースデータをスクレイピングしDataFrameで返す

        Args:
            use_entries: Trueなら出馬表(DebaTable)から取得（予渮用）。
                         Falseなら成績表(RaceMarkTable)から取得（結果分析用）。
        """
        all_records = []
        current = start_date

        while current <= end_date:
            races = self.get_race_list(current)
            for race in races:
                if use_entries:
                    records = self.get_race_entries(current, race["race_no"])
                else:
                    records = self.get_race_result(current, race["race_no"])
                all_records.extend(records)

            current += timedelta(days=1)

        if not all_records:
            logger.warning("データが取得できませんでした")
            return pd.DataFrame()

        df = pd.DataFrame(all_records)
        return df

    def save_data(self, df: pd.DataFrame, filename: str = "race_results.csv"):
        """データをCSVに保存する"""
        filepath = RAW_DATA_DIR / filename
        df.to_csv(filepath, index=False, encoding="utf-8-sig")
        logger.info("保存完了: %s (%d 件)", filepath, len(df))
        return filepath
