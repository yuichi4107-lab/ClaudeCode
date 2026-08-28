"""autorace.jp オッズ(Odds) JSON API のパーサ。

POST /race_info/Odds {placeCode, raceDate, raceNo} の応答から、
2連単(rtwOddsList)・単勝(tnsOddsList)オッズと、発売時点の出走選手情報
(試走タイム・平均ST)を取り出す。result_parser / program_parser と同じ
防御的パターン(欠損・不正値は warnings で続行)。

オッズ値は文字列("23.1")で、欠車・発売対象外の組は欠測または "0.0" に
なりうるため、parse_float で変換したうえで 0 以下は捨てる。
"""

from .result_parser import _first_error_code, _first_error_message

from . import normalize


def parse_api_odds(odds_json: dict, url_meta: dict) -> dict:
    """Odds API 応答をパースして dict を返す。

    odds_json は API 応答の全体({"result": ..., "errors": [...], "body": ...})。
    url_meta = {"venue": ..., "date": "YYYY-MM-DD", "race_no": int}

    返り値: {"status_code": int|None,   # 0=中間オッズ, 1=最終オッズ
             "updated_at": str|None,    # salesInfo.updateDate
             "exacta": [{"first": int, "second": int, "odds": float}, ...],
             "win": [{"car_no": int, "odds": float}, ...],
             "players": [{"car_no", "player_no", "trial_time", "st_ave",
                          "is_absent"}, ...],
             "warnings": [...]}
    失敗時のみ {"error": ..., "error_code": ..., "warnings": [...]}。
    """
    warnings: list[str] = []

    if not isinstance(odds_json, dict):
        return {"error": "odds API応答がdictではありません", "warnings": warnings}

    if odds_json.get("result") != "Success":
        code = _first_error_code(odds_json)
        message = _first_error_message(odds_json)
        return {
            "error": f"odds API Failure (code={code}: {message})",
            "error_code": code,
            "warnings": warnings,
        }

    body = odds_json.get("body")
    if not isinstance(body, dict):
        return {"error": "odds API bodyがdictではありません", "warnings": warnings}

    status_code = normalize.parse_int(body.get("statusCode"))
    sales_info = body.get("salesInfo")
    updated_at = None
    if isinstance(sales_info, dict):
        updated_at = _clean_str(sales_info.get("updateDate"))
    else:
        warnings.append("salesInfo がありません(updated_at は None)")

    exacta = _parse_exacta(body.get("rtwOddsList"), warnings)
    win = _parse_win(body.get("tnsOddsList"), warnings)
    players = _parse_players(body.get("playerList"), warnings)

    if not exacta and not win:
        return {"error": "有効なオッズがありません", "warnings": warnings}

    return {
        "status_code": status_code,
        "updated_at": updated_at,
        "exacta": exacta,
        "win": win,
        "players": players,
        "warnings": warnings,
    }


# ----------------------------------------------------------------- odds

def _parse_exacta(rtw, warnings: list[str]) -> list[dict]:
    """rtwOddsList(dict of dict: [1着車番][2着車番] -> オッズ文字列)を展開する。"""
    if rtw is None:
        warnings.append("rtwOddsList がありません")
        return []
    if not isinstance(rtw, dict):
        warnings.append("rtwOddsList がdictではありません")
        return []

    rows = []
    for first_key, seconds in rtw.items():
        first = normalize.parse_int(first_key)
        if first is None:
            warnings.append(f"rtwOddsList: 1着車番 {first_key!r} を解決できません")
            continue
        if not isinstance(seconds, dict):
            warnings.append(f"rtwOddsList[{first}] がdictではありません")
            continue
        for second_key, value in seconds.items():
            second = normalize.parse_int(second_key)
            if second is None or second == first:
                continue
            odds = normalize.parse_float(value)
            if odds is None or odds <= 0:
                continue  # 欠車・発売対象外("0.0" や非数値)は捨てる
            rows.append({"first": first, "second": second, "odds": odds})
    return rows


def _parse_win(tns, warnings: list[str]) -> list[dict]:
    """tnsOddsList(dict: 車番 -> オッズ文字列)を展開する。"""
    if tns is None:
        warnings.append("tnsOddsList がありません")
        return []
    if not isinstance(tns, dict):
        warnings.append("tnsOddsList がdictではありません")
        return []

    rows = []
    for car_key, value in tns.items():
        car_no = normalize.parse_int(car_key)
        if car_no is None:
            warnings.append(f"tnsOddsList: 車番 {car_key!r} を解決できません")
            continue
        odds = normalize.parse_float(value)
        if odds is None or odds <= 0:
            continue
        rows.append({"car_no": car_no, "odds": odds})
    return rows


# --------------------------------------------------------------- players

def _parse_players(player_list, warnings: list[str]) -> list[dict]:
    """playerList から事前予想用の選手情報(試走タイム・平均ST)を取り出す。"""
    if not isinstance(player_list, list):
        if player_list is not None:
            warnings.append("playerList がlistではありません")
        return []

    players = []
    for row_idx, row in enumerate(player_list):
        if not isinstance(row, dict):
            warnings.append(f"playerList行{row_idx}: dictではないためスキップしました")
            continue
        car_no = normalize.parse_int(row.get("carNo"))
        if car_no is None:
            warnings.append(f"playerList行{row_idx}: carNo を解決できずスキップしました")
            continue
        trial_time, is_retrial = normalize.trial_from_api(
            row.get("trialTime"), row.get("trialRetryCode"))
        players.append({
            "car_no": car_no,
            "player_no": normalize.parse_int(row.get("playerCode")),
            "player_name": _clean_str(row.get("playerName")),
            "handicap": normalize.parse_int(row.get("handicap")),
            "trial_time": trial_time,
            "is_retrial": is_retrial,
            "st_ave": normalize.parse_float(row.get("stAve")),
            "is_absent": 1 if _clean_str(row.get("absent")) else 0,
        })
    return players


def _clean_str(value) -> str | None:
    if not isinstance(value, str):
        return None
    v = value.strip()
    return v or None
