"""当日予想サービス: 出走表APIから特徴量を組み、勝率と2連単確率を出す。

- 対象レースが DB に結果として保存済みならその行を使う(過去日の検証用)。
- 未保存(当日・未確定)なら Program API + OtherRaceInfo を叩いて
  疑似 entries を組み立てる(試走タイムは発走前に公表され次第 API に載る。
  未公表なら NaN のまま予測する — LightGBM は欠損を扱える)。
- 能力指標は SnapshotStore(対象日の月初時点・過去365日)で付与する。
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from autorace_evaluator.config import settings
from autorace_evaluator.model import predictor
from autorace_evaluator.model.features import SnapshotStore, build_features
from autorace_evaluator.parsers.odds_parser import parse_api_odds
from autorace_evaluator.parsers.program_parser import parse_api_program
from autorace_evaluator.parsers import normalize
from autorace_evaluator.scraper.base import BaseScraper
from autorace_evaluator.storage import database, repository

logger = logging.getLogger(__name__)


def load_entries_df(conn, from_date: str, to_date: str) -> pd.DataFrame:
    rows = repository.get_entries_with_race(conn, from_date, to_date)
    return pd.DataFrame([dict(r) for r in rows])


def train_and_save(db_path: str | None = None, before_date: str | None = None,
                   model_path: str = predictor.MODEL_PATH) -> predictor.RankModel:
    """DB全期間(before_date 指定時はそれより前)で学習して保存する。"""
    conn = database.get_connection(db_path or settings.DB_PATH)
    try:
        entries = load_entries_df(conn, "1970-01-01", before_date or "9999-12-31")
    finally:
        conn.close()
    if before_date:
        entries = entries[entries["race_date"] < before_date]
    if entries.empty:
        raise RuntimeError("学習データがありません。先に scrape を実行してください")

    store = SnapshotStore(entries)
    feats = build_features(entries, store=store)
    model = predictor.train(feats)
    predictor.save_model(model, model_path)
    logger.info("model saved: %s", model_path)
    return model


def _fetch_odds(scraper: BaseScraper, venue: str, date: str, race_no: int,
                payload: dict) -> dict | None:
    """Odds API を1レース分叩いてパース結果を返す。取得できなければ None。"""
    try:
        odds_json = scraper.post_json(settings.BASE_URLS["api_odds"], payload)
    except Exception as exc:  # noqa: BLE001 - オッズ無しでも予想は続行する
        logger.warning("オッズ取得失敗 %s R%d: %s", venue, race_no, exc)
        return None
    if not odds_json:
        return None
    meta = {"venue": venue, "date": date, "race_no": race_no}
    parsed = parse_api_odds(odds_json, meta)
    if parsed.get("error"):
        logger.info("オッズ未取得 %s R%d: %s", venue, race_no, parsed["error"])
        return None
    return parsed


def _fetch_program_entries(
    scraper: BaseScraper, venue: str, date: str
) -> tuple[list[dict], dict]:
    """Program API を race_no=1 から順に叩き、疑似 entries 行とオッズを返す。

    返り値: (rows, odds_by_race)
    odds_by_race = {race_id: {"status_code", "updated_at",
                              "exacta": {(first, second): odds},
                              "win": {car_no: odds}}}
    """
    rows = []
    odds_by_race: dict[str, dict] = {}
    for race_no in range(1, settings.MAX_RACE_NO + 1):
        payload = {
            "placeCode": settings.PLACE_CODES[venue],
            "raceDate": date,
            "raceNo": race_no,
        }
        program = scraper.post_json(settings.BASE_URLS["api_program"], payload)
        meta = {"venue": venue, "date": date, "race_no": race_no}
        parsed = parse_api_program(program, meta) if program else {"error": "404"}
        if parsed.get("error"):
            if parsed.get("error_code") == settings.API_CODE_NO_DATA or program is None:
                break  # レース番号が尽きた
            logger.warning("Program 取得失敗 %s R%d: %s", venue, race_no, parsed["error"])
            continue

        other = scraper.post_json(settings.BASE_URLS["api_other_race_info"], payload)
        other_body = (other or {}).get("body") if isinstance(other, dict) else {}
        if not isinstance(other_body, dict):
            other_body = {}
        track_status = (
            normalize.track_status_from_code(other_body.get("raceSituationCode"))
            or normalize.track_status_from_code(other_body.get("situationCode"))
            or settings.TRACK_GOOD
        )

        race_id = f"{venue}_{date}_{race_no}"

        # オッズAPI(1リクエスト追加)。試走タイムは出走表より新しいので上書きする
        odds = _fetch_odds(scraper, venue, date, race_no, payload)
        trial_override = {}
        if odds:
            odds_by_race[race_id] = {
                "status_code": odds.get("status_code"),
                "updated_at": odds.get("updated_at"),
                "exacta": {(r["first"], r["second"]): r["odds"]
                           for r in odds.get("exacta", [])},
                "win": {r["car_no"]: r["odds"] for r in odds.get("win", [])},
            }
            trial_override = {
                p["car_no"]: p["trial_time"] for p in odds.get("players", [])
                if p.get("trial_time") is not None
            }

        for e in parsed["entries"]:
            if e.get("is_absent"):
                continue
            rows.append({
                "race_id": race_id, "race_date": date, "venue": venue,
                "race_no": race_no, "car_no": e["car_no"],
                "player_no": e.get("player_no"),
                "player_name": e.get("player_name"),
                "handicap": e.get("handicap"),
                "trial_time": trial_override.get(e["car_no"], e.get("trial_time")),
                "bike_class": e.get("bike_class"),
                "graduation_code": e.get("graduation_code"),
                "player_rank": e.get("player_rank"),
                "age": e.get("age"),
                "rate2": e.get("rate2"), "rate3": e.get("rate3"),
                "track_status": track_status,
                "trial_track_status": track_status,
                "status": settings.STATUS_FINISHED,
                "finish_pos": np.nan, "st": np.nan, "is_flying": 0,
                "is_retrial": 0, "race_time": np.nan, "last_lap_time": np.nan,
                "meeting_id": None, "distance": other_body.get("distance"),
            })
    return rows, odds_by_race


def _load_odds_from_db(conn, date: str, venue: str) -> dict:
    """DB(exacta_odds)から対象日・会場のオッズを読み、odds_by_race 形式で返す。"""
    odds_by_race: dict[str, dict] = {}
    for row in repository.get_exacta_odds(conn, date, date, venue):
        info = odds_by_race.setdefault(row["race_id"], {
            "status_code": row["status_code"],
            "updated_at": row["updated_at"],
            "exacta": {},
            "win": {},
        })
        odds = row["odds"]
        if odds is not None and odds > 0:
            info["exacta"][(row["first"], row["second"])] = odds
    return odds_by_race


def predict_day(date: str, venue: str,
                db_path: str | None = None,
                race_no: int | None = None,
                use_cache: bool = False,
                model_path: str = predictor.MODEL_PATH) -> dict:
    """指定日・会場の予想を返す。

    返り値: {"win": DataFrame, "exacta": DataFrame, "source": "db"|"api",
             "odds_status": {race_id: {"status_code", "updated_at"}}}
    win: race_id, race_no, car_no, player_name, p_win(レース内降順)
    exacta: race_id ごとの2連単上位(prob 降順)。オッズを取得できた組には
            odds 列と ev 列(= prob × odds)が入る(欠測は NaN)。
    """
    conn = database.get_connection(db_path or settings.DB_PATH)
    try:
        database.init_db(conn)  # オッズ表が無い旧DBでも読めるようにする
        # 学習・スナップショット用の過去データ(対象日より前)
        history = load_entries_df(conn, "1970-01-01", "9999-12-31")
        history = history[history["race_date"] < date]

        # 対象レース: DBにあればそれを、なければ出走表APIから
        target = load_entries_df(conn, date, date)
        if not target.empty:
            target = target[target["venue"] == venue]
        # DB由来(過去レース検証)なら保存済みオッズを使う
        odds_by_race = _load_odds_from_db(conn, date, venue) if not target.empty else {}
    finally:
        conn.close()

    if target.empty:
        scraper = BaseScraper(use_cache=use_cache)
        rows, odds_by_race = _fetch_program_entries(scraper, venue, date)
        if not rows:
            raise RuntimeError(
                f"{date} {venue} の出走表を取得できません(未発表または非開催)")
        target = pd.DataFrame(rows)
        source = "api"
    else:
        source = "db"

    if race_no is not None:
        target = target[target["race_no"] == race_no]
        if target.empty:
            raise RuntimeError(f"レース {race_no}R のデータがありません")

    model = predictor.load_model(model_path)
    if model is None:
        logger.info("学習済みモデルが無いため学習します(%s より前の全データ)", date)
        model = train_and_save(db_path=db_path, before_date=date,
                               model_path=model_path)

    store = SnapshotStore(history)
    feats = build_features(target, store=store)
    feats["p_win"] = model.win_probabilities(feats)

    win = feats[["race_id", "race_no", "car_no", "player_name", "p_win"]] \
        .sort_values(["race_no", "p_win"], ascending=[True, False]) \
        .reset_index(drop=True)
    exacta = predictor.exacta_probabilities(feats[["race_id", "car_no", "p_win"]])
    exacta = _attach_odds(exacta, odds_by_race)
    odds_status = {
        race_id: {"status_code": info.get("status_code"),
                  "updated_at": info.get("updated_at")}
        for race_id, info in odds_by_race.items()
    }
    return {"win": win, "exacta": exacta, "source": source,
            "odds_status": odds_status}


def _attach_odds(exacta: pd.DataFrame, odds_by_race: dict) -> pd.DataFrame:
    """2連単DataFrameに odds 列と ev 列(= prob × odds)を付ける。"""
    if exacta.empty:
        exacta = exacta.copy()
        exacta["odds"] = pd.Series(dtype=float)
        exacta["ev"] = pd.Series(dtype=float)
        return exacta

    exacta = exacta.copy()
    exacta["odds"] = [
        odds_by_race.get(r.race_id, {}).get("exacta", {}).get(
            (int(r.first), int(r.second)), np.nan)
        for r in exacta.itertuples(index=False)
    ]
    exacta["odds"] = pd.to_numeric(exacta["odds"], errors="coerce")
    exacta["ev"] = exacta["prob"] * exacta["odds"]
    return exacta
