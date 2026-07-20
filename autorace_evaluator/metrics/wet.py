"""湿走路(雨)適性: 湿走路限定の期待着順残差 + 良走路との差分(雨巧者度)。

- wet_perf: 湿走路レースで fit した期待着順モデル(finish ~ trial + handicap、
  レース内センタリング + Ridge = attack.fit_expected_finish_model の再利用)の
  残差の選手平均(符号反転: 正 = 期待より前でゴール)を経験ベイズ縮約したもの。
- good_perf: 同型モデルを良走路で fit した対応値。
- wet_gap = wet_perf − good_perf: 正なら「良走路の自分より雨で走る」雨巧者度。
  2つの推定誤差の差でノイジーなため生値の参考列とし、zscore はしない。
- wet_score = zscore(wet_perf)(湿走路出走数 min_wet 以上の選手のみ)。

湿走路は全レースの2割程度しかないため、縮約kは既定より弱い
settings.SHRINKAGE_K_WET を使う。
"""

import numpy as np
import pandas as pd

from autorace_evaluator.config import settings
from autorace_evaluator.metrics.attack import fit_expected_finish_model
from autorace_evaluator.metrics.common import shrink, zscore
from autorace_evaluator.metrics.start_power import compute_st_stats

_PER_PLAYER_COLS = [
    "player_no", "player_name", "n_wet", "wet_perf", "n_good_ref",
    "good_perf", "wet_gap", "mean_st_wet", "wet_score",
]


def _residual_means(sample: pd.DataFrame, k: int) -> pd.DataFrame:
    """fit_expected_finish_model のサンプルから選手別の縮約済み残差平均を返す。"""
    if sample.empty:
        return pd.DataFrame(columns=["player_no", "n", "perf"])
    grouped = sample.groupby("player_no")["attack_residual"]
    out = pd.DataFrame({
        "player_no": grouped.mean().index,
        "n": grouped.size().to_numpy(),
        # 残差が負 = 期待より前で着 = プラス評価 → 符号反転して縮約
        "perf_raw": (-grouped.mean()).to_numpy(),
    })
    out["perf"] = shrink(out["perf_raw"], out["n"], k=k, center=0.0)
    return out[["player_no", "n", "perf"]]


def compute_wet(entries_df: pd.DataFrame,
                min_wet: int = settings.MIN_WET_RACES,
                k: int = settings.SHRINKAGE_K_WET):
    """選手別の湿走路適性テーブルと診断情報を返す。

    Returns:
        per_player: _PER_PLAYER_COLS の DataFrame
        diagnostics: {"wet": {...}, "good": {...}}(各モデルの n_samples/betas)
    """
    df = entries_df[entries_df["player_no"].notna()]

    sample_wet, diag_wet = fit_expected_finish_model(
        df, track_status=settings.TRACK_WET)
    sample_good, diag_good = fit_expected_finish_model(df)

    wet = _residual_means(sample_wet, k=k).rename(
        columns={"n": "n_wet", "perf": "wet_perf"})
    good = _residual_means(sample_good, k=k).rename(
        columns={"n": "n_good_ref", "perf": "good_perf"})

    per_player = wet.merge(good, on="player_no", how="outer")
    if per_player.empty:
        return pd.DataFrame(columns=_PER_PLAYER_COLS), {
            "wet": diag_wet, "good": diag_good}

    per_player["wet_gap"] = per_player["wet_perf"] - per_player["good_perf"]

    st_stats = compute_st_stats(entries_df)
    if not st_stats.empty and "mean_st_wet" in st_stats.columns:
        per_player = per_player.merge(
            st_stats[["player_no", "player_name", "mean_st_wet"]],
            on="player_no", how="left")
    else:
        per_player["player_name"] = None
        per_player["mean_st_wet"] = np.nan

    eligible = per_player["n_wet"].fillna(0) >= min_wet
    per_player["wet_score"] = zscore(per_player["wet_perf"].where(eligible))

    for c in _PER_PLAYER_COLS:
        if c not in per_player.columns:
            per_player[c] = np.nan
    per_player = per_player[_PER_PLAYER_COLS]

    return per_player, {"wet": diag_wet, "good": diag_good}
