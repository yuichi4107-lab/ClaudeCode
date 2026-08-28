"""autorace.jp 出走表(Program) JSON API のパーサ。

POST /race_info/Program {placeCode, raceDate, raceNo} の応答から、
選手属性(車級・期別・級班・年齢・連対率)を取り出す。result_parser と
同じ防御的パターン(欠損・未知値は warnings で続行)。
"""

from .result_parser import _first_error_code, _first_error_message

from . import normalize


def parse_api_program(program_json: dict, url_meta: dict) -> dict:
    """Program API 応答をパースして dict を返す。

    program_json は API 応答の全体({"result": ..., "errors": [...], "body": ...})。
    url_meta = {"venue": ..., "date": "YYYY-MM-DD", "race_no": int}

    返り値: {"entries": [{car_no, player_no, bike_class, graduation_code,
                           player_rank, age, rate2, rate3}, ...],
             "warnings": [...]}
    失敗時のみ {"error": ..., "error_code": ..., "warnings": [...]}。
    """
    warnings: list[str] = []

    if not isinstance(program_json, dict):
        return {"error": "program API応答がdictではありません", "warnings": warnings}

    if program_json.get("result") != "Success":
        code = _first_error_code(program_json)
        message = _first_error_message(program_json)
        return {
            "error": f"program API Failure (code={code}: {message})",
            "error_code": code,
            "warnings": warnings,
        }

    body = program_json.get("body")
    if not isinstance(body, dict):
        return {"error": "program API bodyがdictではありません", "warnings": warnings}

    player_list = body.get("playerList")
    if not isinstance(player_list, list) or not player_list:
        return {"error": "playerList が空です", "warnings": warnings}

    entries = []
    for row_idx, row in enumerate(player_list):
        if not isinstance(row, dict):
            warnings.append(f"行{row_idx}: dictではないためスキップしました")
            continue
        car_no = normalize.parse_int(row.get("carNo"))
        if car_no is None:
            warnings.append(f"行{row_idx}: carNo を解決できずスキップしました")
            continue
        entries.append({
            "car_no": car_no,
            "player_no": normalize.parse_int(row.get("playerCode")),
            "bike_class": normalize.bike_class_from_code(row.get("bikeClass")),
            "graduation_code": normalize.parse_int(row.get("graduationCode")),
            "player_rank": _clean_str(row.get("rank")),
            "age": normalize.parse_int(row.get("age")),
            "rate2": normalize.parse_float(row.get("rate2")),
            "rate3": normalize.parse_float(row.get("rate3")),
            # 以下は事前予想(当日出走表からの推論)用の追加情報。
            # DBの race_entries 更新には使わない(結果APIが正となるため)
            "player_name": _clean_str(row.get("playerName")),
            "handicap": normalize.parse_int(row.get("handicap")),
            "trial_time": normalize.parse_float(row.get("trialRunTime")),
            "is_absent": 1 if _clean_str(row.get("absent")) else 0,
        })

    if not entries:
        return {"error": "有効な出走行がありません", "warnings": warnings}

    return {"entries": entries, "warnings": warnings}


def _clean_str(value) -> str | None:
    if not isinstance(value, str):
        return None
    v = value.strip()
    return v or None
