"""autorace.jp レース結果ページのパーサ。

DOM 構造は parsers/selectors.py の定数経由でのみ参照する。実HTML未確認の
ため、セレクタ不一致・見出し不明・セル欠損はすべて例外にせず None +
warnings で続行する「防御的パーサ」として実装している。
"""

import re

from bs4 import BeautifulSoup

from autorace_evaluator.config import settings

from . import normalize, selectors

# 選手名セル内の <a href> から登録番号を取り出す(例: ".../PlayerInfo/12345/")
_PLAYER_NO_HREF_RE = re.compile(r"/(\d{4,5})/?$")

# レースヘッダテキストから距離(m)を取り出す
_DISTANCE_RE = re.compile(r"(\d{3,4})\s*m", re.IGNORECASE)


def parse_race_result(html: str, url_meta: dict) -> dict:
    """レース結果HTMLをパースして dict を返す。

    url_meta = {"venue": ..., "date": "YYYY-MM-DD", "race_no": int}

    返り値: {"race": {...}, "entries": [...], "payouts": [...], "warnings": [...]}
    必須フィールド car_no が解決できない場合のみ {"error": ..., "warnings": [...]}。
    """
    warnings: list[str] = []
    venue = url_meta.get("venue")
    date = url_meta.get("date")
    race_no = url_meta.get("race_no")
    race_id = f"{venue}_{date}_{race_no}"

    soup = BeautifulSoup(html, "lxml")

    table = soup.select_one(selectors.SELECTORS["result_table"])
    if table is None:
        warnings.append("結果テーブルが見つかりません")
        return {"error": "result table not found", "warnings": warnings}

    rows = table.find_all("tr")
    if not rows:
        warnings.append("結果テーブルに行がありません")
        return {"error": "result table has no rows", "warnings": warnings}

    col_index_map = _build_header_map(rows[0], warnings)

    if "car_no" not in col_index_map.values():
        warnings.append("car_no 列を解決できません")
        return {"error": "car_no column not resolved", "warnings": warnings}

    entries = []
    for row_idx, tr in enumerate(rows[1:]):
        entry = _parse_entry_row(tr, row_idx, col_index_map, race_id, warnings)
        if entry is not None:
            entries.append(entry)

    field_size = sum(1 for e in entries if e["status"] != settings.STATUS_SCRATCHED)

    header_el = soup.select_one(selectors.SELECTORS["race_header"])
    if header_el is None:
        warnings.append("レースヘッダが見つかりません")
        header_text = ""
    else:
        header_text = header_el.get_text(" ", strip=True)
    race_name = header_text or None
    distance = _extract_distance(header_text)

    weather_el = soup.select_one(selectors.SELECTORS["weather_block"])
    weather_info = _extract_weather(weather_el, warnings)

    payouts = _extract_payouts(soup)

    race = {
        "race_id": race_id,
        "venue": venue,
        "race_date": date,
        "race_no": race_no,
        "race_name": race_name,
        "distance": distance,
        "weather": weather_info["weather"],
        "track_status": weather_info["track_status"],
        "temperature": weather_info["temperature"],
        "track_temp": weather_info["track_temp"],
        "meeting_id": None,
        "field_size": field_size,
        "source_url": url_meta.get("source_url"),
    }

    return {"race": race, "entries": entries, "payouts": payouts, "warnings": warnings}


# ------------------------------------------------------------ header map

def _build_header_map(header_row, warnings: list[str]) -> dict[int, str]:
    """テーブルヘッダ行のセルを HEADER_FIELD_MAP で列index→フィールド名に対応づける。"""
    col_index_map: dict[int, str] = {}
    header_cells = header_row.find_all(["th", "td"])
    for idx, cell in enumerate(header_cells):
        header_text = normalize.zen_to_han(cell.get_text(strip=True))
        field = _match_field(header_text, selectors.HEADER_FIELD_MAP)
        if field:
            col_index_map[idx] = field
        else:
            warnings.append(f"見出し不明(列{idx}): {header_text!r}")
    return col_index_map


def _match_field(label: str, field_map: dict) -> str | None:
    """label を field_map の同義語リストに照合してフィールド名を返す。

    完全一致を優先し、なければ最長の部分一致を採用する。
    """
    if not label:
        return None
    for field, synonyms in field_map.items():
        if label in synonyms:
            return field
    best_field, best_len = None, 0
    for field, synonyms in field_map.items():
        for syn in synonyms:
            if syn and syn in label and len(syn) > best_len:
                best_field, best_len = field, len(syn)
    return best_field


# ----------------------------------------------------------------- rows

def _parse_entry_row(
    tr, row_idx: int, col_index_map: dict[int, str], race_id: str, warnings: list[str]
) -> dict | None:
    cells = tr.find_all(["td", "th"])
    cell_map = {}
    for idx, field in col_index_map.items():
        cell_map[field] = cells[idx] if idx < len(cells) else None

    def _text(field: str) -> str | None:
        cell = cell_map.get(field)
        return cell.get_text(strip=True) if cell is not None else None

    car_no = normalize.parse_handicap(_text("car_no"))
    if car_no is None:
        warnings.append(f"行{row_idx}: car_no を解決できずスキップしました")
        return None

    finish_pos, status, violation_from_finish = normalize.parse_finish(_text("finish_pos"))
    handicap = normalize.parse_handicap(_text("handicap"))
    trial_time, is_retrial = normalize.parse_trial_time(_text("trial_time"))
    race_time = normalize.parse_float(_text("race_time"))
    last_lap_time = normalize.parse_float(_text("last_lap_time"))
    st, is_flying = normalize.parse_st(_text("st"))

    violation_col_text = _text("violation_note")
    violation_note = violation_col_text if violation_col_text else violation_from_finish

    player_name_cell = cell_map.get("player_name")
    player_name = player_name_cell.get_text(strip=True) if player_name_cell is not None else None

    player_no = _extract_player_no(cell_map.get("player_no"), player_name_cell, row_idx, warnings)

    return {
        "race_id": race_id,
        "car_no": car_no,
        "player_no": player_no,
        "player_name": player_name,
        "handicap": handicap,
        "trial_time": trial_time,
        "is_retrial": is_retrial,
        "race_time": race_time,
        "last_lap_time": last_lap_time,
        "st": st,
        "is_flying": is_flying,
        "finish_pos": finish_pos,
        "status": status,
        "violation_note": violation_note,
    }


def _extract_player_no(player_no_cell, player_name_cell, row_idx: int, warnings: list[str]):
    """選手登録番号を抽出する。

    1. (もしあれば)登録番号専用セルの数字
    2. 選手名セル内の a[href] から /(\\d{4,5})/? パターン
    3. 選手名セル内のテキストに含まれる数字
    4. どれも取れなければ None(warnings追記)
    """
    if player_no_cell is not None:
        digits = re.search(r"\d+", normalize.zen_to_han(player_no_cell.get_text(strip=True)) or "")
        if digits:
            return int(digits.group())

    if player_name_cell is not None:
        anchor = player_name_cell.find("a", href=True)
        if anchor is not None:
            m = _PLAYER_NO_HREF_RE.search(anchor["href"])
            if m:
                return int(m.group(1))
        digits = re.search(r"\d{3,5}", normalize.zen_to_han(player_name_cell.get_text(strip=True)) or "")
        if digits:
            return int(digits.group())

    warnings.append(f"行{row_idx}: 選手登録番号を解決できません")
    return None


# ------------------------------------------------------------- distance

def _extract_distance(header_text: str) -> int | None:
    if not header_text:
        return None
    normalized = normalize.zen_to_han(header_text)
    m = _DISTANCE_RE.search(normalized)
    if not m:
        return None
    return int(m.group(1))


# -------------------------------------------------------------- weather

def _extract_weather(weather_el, warnings: list[str]) -> dict:
    raw = {"weather": None, "track_status": None, "temperature": None, "track_temp": None}

    if weather_el is None:
        warnings.append("気象ブロックが見つかりません")
        return {"weather": None, "track_status": None, "temperature": None, "track_temp": None}

    pairs: list[tuple[str, str | None]] = []
    dt_list = weather_el.find_all("dt")
    if dt_list:
        for dt in dt_list:
            dd = dt.find_next_sibling("dd")
            label = normalize.zen_to_han(dt.get_text(strip=True))
            value = dd.get_text(strip=True) if dd is not None else None
            pairs.append((label, value))
    else:
        text = weather_el.get_text(" ", strip=True)
        for token in text.split():
            norm_token = normalize.zen_to_han(token).replace("：", ":")
            if ":" in norm_token:
                label, _, value = norm_token.partition(":")
                pairs.append((label, value))

    matched_any = False
    for label, value in pairs:
        field = _match_field(label, selectors.WEATHER_FIELD_MAP)
        if field is None:
            warnings.append(f"気象ラベル不明: {label!r}")
            continue
        raw[field] = value
        matched_any = True

    if not matched_any:
        warnings.append("気象ブロックの値を抽出できません")

    return {
        "weather": raw["weather"],
        "track_status": normalize.parse_track_status(raw["track_status"]),
        "temperature": normalize.parse_temperature(raw["temperature"]),
        "track_temp": normalize.parse_temperature(raw["track_temp"]),
    }


# -------------------------------------------------------------- payouts

def _extract_payouts(soup) -> list[dict]:
    table = soup.select_one(selectors.SELECTORS["payout_table"])
    if table is None:
        return []

    payouts = []
    for tr in table.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        if len(cells) < 3:
            continue
        if tr.find("td") is None:
            # 全セルが th のヘッダ行はスキップ
            continue
        bet_type = cells[0].get_text(strip=True)
        combination = cells[1].get_text(strip=True)
        payout = _parse_payout_amount(cells[2].get_text(strip=True))
        if not bet_type or not combination:
            continue
        payouts.append({"bet_type": bet_type, "combination": combination, "payout": payout})
    return payouts


def _parse_payout_amount(text: str | None) -> float | None:
    if text is None:
        return None
    t = normalize.zen_to_han(text)
    t = re.sub(r"[^\d.]", "", t or "")
    if not t:
        return None
    try:
        return float(t)
    except ValueError:
        return None
