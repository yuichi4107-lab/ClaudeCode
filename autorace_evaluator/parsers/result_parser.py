"""autorace.jp レース結果 JSON API のパーサ。

API仕様は parsers/selectors.py のモジュールドキュメント参照。フィールド欠損・
未知コードはすべて例外にせず None + warnings で続行する「防御的パーサ」。
"""

from autorace_evaluator.config import settings

from . import normalize, selectors


def parse_api_race_result(
    result_json: dict,
    other_json: dict | None,
    url_meta: dict,
) -> dict:
    """RaceResult / OtherRaceInfo API 応答をパースして dict を返す。

    result_json / other_json は API 応答の全体
    ({"result": ..., "errors": [...], "body": ...})。other_json は None 可
    (距離・天候・走路状況・節情報が欠けるだけで entries は解析できる)。
    url_meta = {"venue": ..., "date": "YYYY-MM-DD", "race_no": int}

    返り値: {"race": {...}, "entries": [...], "payouts": [...], "warnings": [...]}
    失敗時のみ {"error": ..., "error_code": ..., "warnings": [...]}。
    error_code は API の Failure コード(4101=データなし, 4200=中止)。
    """
    warnings: list[str] = []
    venue = url_meta.get("venue")
    date = url_meta.get("date")
    race_no = url_meta.get("race_no")
    race_id = f"{venue}_{date}_{race_no}"

    if not isinstance(result_json, dict):
        return {"error": "result API応答がdictではありません", "warnings": warnings}

    if result_json.get("result") != "Success":
        code = _first_error_code(result_json)
        message = _first_error_message(result_json)
        return {
            "error": f"result API Failure (code={code}: {message})",
            "error_code": code,
            "warnings": warnings,
        }

    body = result_json.get("body")
    if not isinstance(body, dict):
        return {"error": "result API bodyがdictではありません", "warnings": warnings}

    race_result = body.get("raceResult")
    if not isinstance(race_result, list) or not race_result:
        return {"error": "raceResult が空です", "warnings": warnings}

    entries = []
    for row_idx, row in enumerate(race_result):
        entry = _parse_entry(row, row_idx, race_id, warnings)
        if entry is not None:
            entries.append(entry)

    if not entries:
        return {"error": "有効な出走行がありません", "warnings": warnings}

    field_size = sum(1 for e in entries if e["status"] != settings.STATUS_SCRATCHED)

    other_body = _other_body(other_json, warnings)
    race = _build_race(other_body, venue, date, race_no, race_id, field_size, url_meta)

    payouts = _parse_payouts(body.get("refundInfo"), warnings)

    return {"race": race, "entries": entries, "payouts": payouts, "warnings": warnings}


def _first_error_code(api_json: dict) -> str | None:
    errors = api_json.get("errors")
    if isinstance(errors, list) and errors and isinstance(errors[0], dict):
        code = errors[0].get("code")
        return str(code) if code is not None else None
    return None


def _first_error_message(api_json: dict) -> str | None:
    errors = api_json.get("errors")
    if isinstance(errors, list) and errors and isinstance(errors[0], dict):
        return errors[0].get("message")
    return None


# ----------------------------------------------------------------- entries

def _parse_entry(row, row_idx: int, race_id: str, warnings: list[str]) -> dict | None:
    if not isinstance(row, dict):
        warnings.append(f"行{row_idx}: dictではないためスキップしました")
        return None

    car_no = normalize.parse_int(row.get("carNo"))
    if car_no is None:
        warnings.append(f"行{row_idx}: carNo を解決できずスキップしました")
        return None

    finish_pos, status, note_from_accident = normalize.finish_from_api(
        row.get("order"), row.get("accidentName")
    )
    trial_time, is_retrial = normalize.trial_from_api(
        row.get("traialTime"), row.get("traialRetryCode")
    )
    st, is_flying = normalize.st_from_api(row.get("st"), row.get("foulCode"))

    notes = [n for n in (note_from_accident, normalize.foul_note(row.get("foulCode")))
             if n]
    violation_note = " ".join(notes) if notes else None

    player_no = normalize.parse_int(row.get("playerCode"))
    if player_no is None:
        warnings.append(f"行{row_idx}: playerCode を解決できません")

    player_name = row.get("playerName")
    if isinstance(player_name, str):
        player_name = player_name.strip() or None

    return {
        "race_id": race_id,
        "car_no": car_no,
        "player_no": player_no,
        "player_name": player_name,
        "handicap": normalize.parse_int(row.get("handicap")),
        "trial_time": trial_time,
        "is_retrial": is_retrial,
        "race_time": normalize.parse_float(row.get("raceTime")),
        "last_lap_time": None,  # APIに上がりタイムは掲載されない
        "st": st,
        "is_flying": is_flying,
        "finish_pos": finish_pos,
        "status": status,
        "violation_note": violation_note,
    }


# -------------------------------------------------------------------- race

def _other_body(other_json, warnings: list[str]) -> dict:
    if other_json is None:
        warnings.append("OtherRaceInfo 応答がありません(距離・天候・走路状況は欠損)")
        return {}
    if not isinstance(other_json, dict) or other_json.get("result") != "Success":
        warnings.append("OtherRaceInfo 応答が Success ではありません")
        return {}
    body = other_json.get("body")
    if not isinstance(body, dict):
        warnings.append("OtherRaceInfo body がdictではありません")
        return {}
    return body


def _build_race(other_body: dict, venue, date, race_no, race_id: str,
                field_size: int, url_meta: dict) -> dict:
    # 走路状況: race* が競走時、無印が試走時。track_status には競走時を採用し、
    # 試走時は trial_track_status に別途保持する(整備力指標が参照)。
    track_status = normalize.track_status_from_code(other_body.get("raceSituationCode"))
    trial_track_status = normalize.track_status_from_code(other_body.get("situationCode"))
    if track_status is None:
        track_status = trial_track_status

    title = other_body.get("title")
    race_name = other_body.get("raceName")
    name_parts = [p for p in (title, race_name) if isinstance(p, str) and p.strip()]

    meeting_id = None
    period_start = other_body.get("periodStartDate")
    if isinstance(period_start, str) and period_start:
        meeting_id = f"{venue}_{period_start}"

    return {
        "race_id": race_id,
        "venue": venue,
        "race_date": date,
        "race_no": race_no,
        "race_name": " ".join(name_parts) if name_parts else None,
        "distance": normalize.parse_int(other_body.get("distance")),
        "weather": other_body.get("raceWeather") or other_body.get("weather"),
        "track_status": track_status,
        "trial_track_status": trial_track_status,
        "temperature": normalize.parse_float(
            other_body.get("raceTemp") or other_body.get("temp")),
        "track_temp": normalize.parse_float(
            other_body.get("raceRoadtemp") or other_body.get("roadtemp")),
        "meeting_id": meeting_id,
        "field_size": field_size,
        "source_url": url_meta.get("source_url") or url_meta.get("url"),
    }


# ----------------------------------------------------------------- payouts

def _parse_payouts(refund_info, warnings: list[str]) -> list[dict]:
    if not isinstance(refund_info, dict):
        return []

    payouts = []
    for key, bet_type in selectors.REFUND_BET_TYPES.items():
        block = refund_info.get(key)
        if not isinstance(block, dict):
            continue
        if normalize.parse_int(block.get("typeCode")) != selectors.REFUND_TYPE_NORMAL:
            continue  # 特払い・全返還・無投票等は保存しない
        for item in block.get("list") or []:
            if not isinstance(item, dict):
                continue
            combo = _combination(item)
            payout = normalize.parse_float(item.get("refund"))
            if combo is None or payout is None or payout <= 0:
                continue
            payouts.append(
                {"bet_type": bet_type, "combination": combo, "payout": payout}
            )
    return payouts


def _combination(item: dict) -> str | None:
    cars = []
    for k in ("1thCarNo", "2thCarNo", "3thCarNo"):
        v = normalize.parse_int(item.get(k))
        if v is not None and v > 0:
            cars.append(str(v))
    return "-".join(cars) if cars else None
