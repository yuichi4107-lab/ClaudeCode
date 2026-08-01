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


def _fetch_program_entries(scraper: BaseScraper, venue: str, date: str) -> list[dict]:
    """Program API を race_no=1 から順に叩き、疑似 entries 行のリストを返す。"""
    rows = []
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
        for e in parsed["entries"]:
            if e.get("is_absent"):
                continue
            rows.append({
                "race_id": race_id, "race_date": date, "venue": venue,
                "race_no": race_no, "car_no": e["car_no"],
                "player_no": e.get("player_no"),
                "player_name": e.get("player_name"),
                "handicap": e.get("handicap"),
                "trial_time": e.get("trial_time"),
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
    return rows


def predict_day(date: str, venue: str,
                db_path: str | None = None,
                race_no: int | None = None,
                use_cache: bool = False,
                model_path: str = predictor.MODEL_PATH) -> dict:
    """指定日・会場の予想を返す。

    返り値: {"win": DataFrame, "exacta": DataFrame, "source": "db"|"api"}
    win: race_id, race_no, car_no, player_name, p_win(レース内降順)
    exacta: race_id ごとの2連単上位(prob 降順)
    """
    conn = database.get_connection(db_path or settings.DB_PATH)
    try:
        # 学習・スナップショット用の過去データ(対象日より前)
        history = load_entries_df(conn, "1970-01-01", "9999-12-31")
        history = history[history["race_date"] < date]

        # 対象レース: DBにあればそれを、なければ出走表APIから
        target = load_entries_df(conn, date, date)
        target = target[target["venue"] == venue]
    finally:
        conn.close()

    if target.empty:
        scraper = BaseScraper(use_cache=use_cache)
        rows = _fetch_program_entries(scraper, venue, date)
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
    return {"win": win, "exacta": exacta, "source": source}
