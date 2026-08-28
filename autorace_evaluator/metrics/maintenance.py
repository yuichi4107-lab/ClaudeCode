"""整備力: 同一節内・良走路同士の前日比試走タイム差。

diff = trial(前日) − trial(当日)。正 = 当日のほうが速い = 整備で底上げできた。
"""

from datetime import date, timedelta

import numpy as np
import pandas as pd

from autorace_evaluator.config import settings
from autorace_evaluator.metrics.common import zscore


REQUIRED_COLS = [
    "race_id", "race_no", "race_date", "meeting_id", "track_status",
    "player_no", "player_name", "trial_time", "is_retrial", "status",
]


def build_daily_trials(entries_df: pd.DataFrame, include_retrial: bool = False) -> pd.DataFrame:
    """選手×日ごとの採用試走タイム(その日の最初のレース番号のもの)を返す。

    採用条件: 良走路・trial_time 非NULL・非欠車。
    is_retrial=1 の日は既定で除外(パーサが再試走マークを検出できない間は
    全行0なので実質全件採用)。
    """
    df = entries_df.copy()
    df = df[df["status"] != settings.STATUS_SCRATCHED]
    # 試走は競走より前に行われるため、試走時の走路状況(trial_track_status)を
    # 優先して「良走路」判定する。無ければ競走時の track_status で代用。
    if "trial_track_status" in df.columns:
        trial_track = df["trial_track_status"].fillna(df["track_status"])
    else:
        trial_track = df["track_status"]
    df = df[trial_track == settings.TRACK_GOOD]
    df = df[df["trial_time"].notna()]
    df = df[df["player_no"].notna()]
    if not include_retrial:
        df = df[df["is_retrial"].fillna(0).astype(int) == 0]
    if df.empty:
        return pd.DataFrame(columns=["player_no", "player_name", "meeting_id",
                                     "race_date", "trial_time"])
    # 同日複数走(防御): 最初のレース番号の試走タイムを採用
    df = df.sort_values(["player_no", "race_date", "race_no"])
    daily = df.groupby(["player_no", "meeting_id", "race_date"], as_index=False).first()
    return daily[["player_no", "player_name", "meeting_id", "race_date", "trial_time"]]


def build_pairs(daily: pd.DataFrame) -> pd.DataFrame:
    """同一節・同一選手の連続2暦日 (d-1, d) のペアと diff を返す。"""
    rows = []
    for (player_no, meeting_id), group in daily.groupby(["player_no", "meeting_id"]):
        g = group.sort_values("race_date")
        by_date = {r["race_date"]: r for _, r in g.iterrows()}
        for ds, row in by_date.items():
            prev_ds = (date.fromisoformat(ds) - timedelta(days=1)).isoformat()
            if prev_ds in by_date:
                prev = by_date[prev_ds]
                diff = round(prev["trial_time"] - row["trial_time"],
                             settings.TRIAL_TIME_DECIMALS)
                rows.append({
                    "player_no": player_no,
                    "player_name": row["player_name"],
                    "meeting_id": meeting_id,
                    "date_prev": prev_ds,
                    "date_cur": ds,
                    "trial_prev": prev["trial_time"],
                    "trial_cur": row["trial_time"],
                    "diff": diff,
                })
    cols = ["player_no", "player_name", "meeting_id", "date_prev", "date_cur",
            "trial_prev", "trial_cur", "diff"]
    return pd.DataFrame(rows, columns=cols)


def compute_maintenance(entries_df: pd.DataFrame,
                        include_retrial: bool = False,
                        min_pairs: int = settings.MIN_PAIRS):
    """選手別整備力テーブルと全体分布を返す。

    Returns:
        per_player: player_no, player_name, n_pairs, improved_rate,
                    worsened_rate, same_rate, mean_diff, median_diff,
                    maintenance_score (n_pairs < min_pairs は NaN)
        pairs: 全ペア明細
        overall: 全ペア diff の分布サマリ dict
    """
    daily = build_daily_trials(entries_df, include_retrial=include_retrial)
    pairs = build_pairs(daily)

    if pairs.empty:
        per_player = pd.DataFrame(columns=[
            "player_no", "player_name", "n_pairs", "improved_rate",
            "worsened_rate", "same_rate", "mean_diff", "median_diff",
            "maintenance_score"])
        return per_player, pairs, {"n_pairs": 0}

    pairs = pairs.assign(
        improved=(pairs["diff"] > 0).astype(int),
        worsened=(pairs["diff"] < 0).astype(int),
        same=(pairs["diff"] == 0).astype(int),
    )
    per_player = pairs.groupby("player_no").agg(
        player_name=("player_name", "last"),
        n_pairs=("diff", "size"),
        improved_rate=("improved", "mean"),
        worsened_rate=("worsened", "mean"),
        same_rate=("same", "mean"),
        mean_diff=("diff", "mean"),
        median_diff=("diff", "median"),
    ).reset_index()

    eligible = per_player["n_pairs"] >= min_pairs
    net = per_player["improved_rate"] - per_player["worsened_rate"]
    z_net = zscore(net.where(eligible))
    z_mean = zscore(per_player["mean_diff"].where(eligible))
    per_player["maintenance_score"] = np.where(
        eligible, 0.5 * z_net + 0.5 * z_mean, np.nan)

    diffs = pairs["diff"]
    overall = {
        "n_pairs": int(len(diffs)),
        "improved_rate": float((diffs > 0).mean()),
        "worsened_rate": float((diffs < 0).mean()),
        "same_rate": float((diffs == 0).mean()),
        "mean": float(diffs.mean()),
        "sd": float(diffs.std(ddof=0)),
        "p10": float(diffs.quantile(0.10)),
        "p25": float(diffs.quantile(0.25)),
        "p50": float(diffs.quantile(0.50)),
        "p75": float(diffs.quantile(0.75)),
        "p90": float(diffs.quantile(0.90)),
    }
    return per_player, pairs, overall
