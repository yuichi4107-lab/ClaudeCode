"""予想モデルの特徴量ビルダー。

未来リーク防止の設計:
- 選手の能力指標(整備力・スタート力・突っ込み度・湿走路適性 等)は
  「月初スナップショット」方式で付与する。レース日 d の行には、
  d の属する月の初日より前(最大365日)のデータだけで計算した
  build_report の値を使う。スナップショットは月単位でキャッシュされ、
  ウォークフォワード学習・バックテストと整合する。
- レース行自身から使ってよいのは事前公開情報のみ:
  ハンデ・試走タイム(発走前に公表される)・車級・期別・級班・年齢・
  連対率(出走表由来)・走路状態。ST や着順は使わない。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from autorace_evaluator.config import settings
from autorace_evaluator.metrics import report as report_mod

# 学習・推論で使う特徴量列(この順で行列化する)
FEATURE_COLS = [
    # レース内の事前情報
    "handicap", "trial_time", "trial_rel", "front_cars", "field_size",
    "race_no", "venue_code", "is_wet",
    # 出走表由来の選手属性
    "bike_class_code", "graduation_code", "age", "rate2", "rate3",
    "rank_letter_code", "rank_number",
    # 月初スナップショットの能力指標
    "maintenance_score", "start_score", "attack_score",
    "wet_score", "wet_gap", "mean_st", "attack_a", "mean_passed",
    "pass_rate", "n_races_hist",
]

_SNAPSHOT_COLS = [
    "player_no", "maintenance_score", "start_score", "attack_score",
    "wet_score", "wet_gap", "mean_st", "attack_a", "mean_passed",
    "pass_rate", "n_races",
]

_VENUE_CODES = {v: i for i, v in enumerate(
    settings.VENUE_SLUGS + [settings.TWICE_VENUE_SLUG])}

_RANK_LETTER_CODES = {"S": 0, "A": 1, "B": 2}

SNAPSHOT_WINDOW_DAYS = 365


def month_start(date_str: str) -> str:
    """'2026-07-15' -> '2026-07-01'。スナップショットのキー。"""
    return date_str[:8] + "01"


class SnapshotStore:
    """月初時点の選手指標スナップショットを遅延計算・キャッシュする。"""

    def __init__(self, entries_df: pd.DataFrame):
        # race_date 昇順ソート済みの全期間 entries(結果列を含んでよい —
        # スナップショット計算は必ず月初より前の行に絞ってから行う)
        self._entries = entries_df
        self._cache: dict[str, pd.DataFrame] = {}

    def get(self, snapshot_date: str) -> pd.DataFrame:
        """snapshot_date(YYYY-MM-01)より前・最大365日分で計算した指標表を返す。"""
        if snapshot_date in self._cache:
            return self._cache[snapshot_date]
        window_start = (
            pd.Timestamp(snapshot_date) - pd.Timedelta(days=SNAPSHOT_WINDOW_DAYS)
        ).strftime("%Y-%m-%d")
        past = self._entries[
            (self._entries["race_date"] < snapshot_date)
            & (self._entries["race_date"] >= window_start)
        ]
        if past.empty or past["race_id"].nunique() < 30:
            snap = pd.DataFrame(columns=_SNAPSHOT_COLS)
        else:
            table = report_mod.build_report(past)["table"]
            snap = table[[c for c in _SNAPSHOT_COLS if c in table.columns]].copy()
        self._cache[snapshot_date] = snap
        return snap


def _rank_features(rank: pd.Series) -> tuple[pd.Series, pd.Series]:
    """級班 'A-225' 等を (レター0/1/2, 数字) に分解する。不明は NaN。"""
    s = rank.astype("string")
    letter = s.str.extract(r"^([SAB])", expand=False).map(_RANK_LETTER_CODES)
    number = pd.to_numeric(s.str.extract(r"-(\d+)", expand=False), errors="coerce")
    return letter.astype(float), number


def build_features(entries_df: pd.DataFrame,
                   store: SnapshotStore | None = None) -> pd.DataFrame:
    """entries_df(get_entries_with_race の列構成)から特徴量表を作る。

    返り値は元の識別列(race_id, race_date, car_no, player_no, player_name,
    finish_pos, status)+ FEATURE_COLS。ST・着順は特徴量に含めない。
    store を渡すと選手指標スナップショットを付与する(None ならスキップ =
    テスト用途)。
    """
    df = entries_df.copy()
    df = df[df["player_no"].notna()]
    df = df[df["status"] != settings.STATUS_SCRATCHED]

    # レース内相対量
    df["trial_rel"] = df["trial_time"] - df.groupby("race_id")["trial_time"].transform("mean")
    df["field_size"] = df.groupby("race_id")["car_no"].transform("size")
    h = df["handicap"]
    df["front_cars"] = (
        df.groupby("race_id")["handicap"]
        .transform(lambda s: s.rank(method="min") - 1)
        .where(h.notna())
    )

    df["venue_code"] = df["venue"].map(_VENUE_CODES).fillna(-1).astype(int)
    df["is_wet"] = (df["track_status"] == settings.TRACK_WET).astype(int)

    if "bike_class" in df.columns:
        df["bike_class_code"] = (df["bike_class"] == "2級車").astype(float).where(
            df["bike_class"].notna())
    else:
        df["bike_class_code"] = np.nan
    for col in ("graduation_code", "age", "rate2", "rate3"):
        if col not in df.columns:
            df[col] = np.nan

    if "player_rank" in df.columns:
        df["rank_letter_code"], df["rank_number"] = _rank_features(df["player_rank"])
    else:
        df["rank_letter_code"] = np.nan
        df["rank_number"] = np.nan

    # 月初スナップショットの能力指標
    snap_cols = [c for c in _SNAPSHOT_COLS if c != "player_no"]
    for c in snap_cols:
        df[c if c != "n_races" else "n_races_hist"] = np.nan
    if store is not None:
        for snap_date, group in df.groupby(df["race_date"].map(month_start)):
            snap = store.get(snap_date)
            if snap.empty:
                continue
            merged = group[["player_no"]].merge(snap, on="player_no", how="left")
            merged.index = group.index
            for c in snap_cols:
                target = "n_races_hist" if c == "n_races" else c
                if c in merged.columns:
                    # nullable dtype(Float64等)を素の float64 に落として代入する
                    df.loc[group.index, target] = pd.to_numeric(
                        merged[c], errors="coerce").astype(float).to_numpy()

    id_cols = ["race_id", "race_date", "venue", "race_no", "car_no",
               "player_no", "player_name", "finish_pos", "status"]
    return df[id_cols + [c for c in FEATURE_COLS if c not in id_cols]]
