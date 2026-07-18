"""スタート力: ST基礎統計 + ダッシュ力(1コーナー進入の速さ)の統計プロキシ。

ダッシュ力は「レース内センタリング + Ridge残差 + 経験ベイズ縮約」で推定する。

着眼: early_loss = per100m(競走タイム) − per100m(上がりタイム) は
「静止発進〜序盤で失った時間 + 序盤の位置取りロス」を集約する。
これを機材速度(試走タイム)・ST・ハンデで説明した残差が、
同条件の他車と比べた「序盤の位置取り力」の推定値になる。
"""

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

from autorace_evaluator.config import settings
from autorace_evaluator.metrics.common import (
    center_within_race, shrink, to_per100m, zscore,
)

MIN_VALID_PER_RACE = 3  # レース内センタリングに必要な最小有効車数


def compute_st_stats(entries_df: pd.DataFrame) -> pd.DataFrame:
    """選手別ST統計。欠車以外でSTが記録された出走を対象。"""
    df = entries_df[entries_df["status"] != settings.STATUS_SCRATCHED].copy()
    df = df[df["player_no"].notna()]
    df["is_flying"] = df["is_flying"].fillna(0).astype(int)

    # フライング率の分母: STが観測された出走 + フライング出走
    started = df[df["st"].notna() | (df["is_flying"] == 1)]
    if started.empty:
        return pd.DataFrame(columns=[
            "player_no", "player_name", "n_st", "mean_st", "median_st",
            "p25_st", "p75_st", "sd_st", "flying_rate",
            "mean_st_good", "mean_st_wet"])

    def _agg(group):
        st = group["st"].dropna()
        good = group.loc[group["track_status"] == settings.TRACK_GOOD, "st"].dropna()
        wet = group.loc[group["track_status"] == settings.TRACK_WET, "st"].dropna()
        return pd.Series({
            "player_name": group["player_name"].iloc[-1],
            "n_st": len(st),
            "mean_st": st.mean() if len(st) else np.nan,
            "median_st": st.median() if len(st) else np.nan,
            "p25_st": st.quantile(0.25) if len(st) else np.nan,
            "p75_st": st.quantile(0.75) if len(st) else np.nan,
            "sd_st": st.std(ddof=0) if len(st) else np.nan,
            "flying_rate": group["is_flying"].mean(),
            "mean_st_good": good.mean() if len(good) else np.nan,
            "mean_st_wet": wet.mean() if len(wet) else np.nan,
        })

    stats = started.groupby("player_no").apply(_agg, include_groups=False).reset_index()
    return stats


def fit_dash_model(entries_df: pd.DataFrame,
                   ridge_alpha: float = settings.RIDGE_ALPHA,
                   with_interaction: bool = False):
    """ダッシュ力残差モデルを学習し、(サンプルdf+残差列, 係数診断dict) を返す。

    サンプル: 良走路・完走・trial/st/race_time/last_lap_time 非NULL・
    レース内有効車数 >= MIN_VALID_PER_RACE。
    """
    df = entries_df.copy()
    mask = (
        (df["track_status"] == settings.TRACK_GOOD)
        & (df["status"] == settings.STATUS_FINISHED)
        & df["trial_time"].notna() & df["st"].notna()
        & df["race_time"].notna() & df["last_lap_time"].notna()
        & df["handicap"].notna() & df["player_no"].notna()
    )
    df = df[mask].copy()
    if df.empty:
        return df.assign(dash_residual=np.nan), {}

    df["early_loss"] = (
        to_per100m(df["race_time"], df["distance"])
        - to_per100m(df["last_lap_time"], df["distance"])
    )
    df = df[df["early_loss"].notna()]

    # レース内有効車数が少ないレースはセンタリングが縮退するので除外
    counts = df.groupby("race_id")["car_no"].transform("size")
    df = df[counts >= MIN_VALID_PER_RACE]
    if df.empty:
        return df.assign(dash_residual=np.nan), {}

    df = center_within_race(df, ["early_loss", "st", "trial_time", "handicap"])

    feature_cols = ["st_c", "trial_time_c", "handicap_c"]
    X = df[feature_cols].to_numpy(dtype=float)
    if with_interaction:
        X = np.column_stack([X, df["st_c"] * df["handicap_c"]])
        feature_cols = feature_cols + ["st_c*handicap_c"]
    y = df["early_loss_c"].to_numpy(dtype=float)

    scaler = StandardScaler()
    # 定数列(全ゼロ等)があると scale=0 になるため防御
    Xs = scaler.fit_transform(X)
    Xs = np.nan_to_num(Xs, nan=0.0, posinf=0.0, neginf=0.0)

    model = Ridge(alpha=ridge_alpha)
    model.fit(Xs, y)
    df["dash_residual"] = y - model.predict(Xs)

    scales = np.where(scaler.scale_ == 0, 1.0, scaler.scale_)
    diagnostics = {
        "n_samples": int(len(df)),
        "n_races": int(df["race_id"].nunique()),
        # 元スケールでの係数(ST 0.01秒あたりの序盤ロス等の妥当性確認用)
        "betas": dict(zip(feature_cols, (model.coef_ / scales).tolist())),
        "beta_st_positive": bool((model.coef_ / scales)[0] > 0),
    }
    return df, diagnostics


def compute_start_power(entries_df: pd.DataFrame,
                        min_races: int = settings.MIN_RACES,
                        k: int = settings.SHRINKAGE_K):
    """選手別スタート力テーブルと診断情報を返す。

    Returns:
        per_player: player_no, player_name, ST統計列, n_dash, dash,
                    st_shrunk, start_score
        diagnostics: ダッシュ力モデルの係数等
    """
    st_stats = compute_st_stats(entries_df)

    sample, diagnostics = fit_dash_model(entries_df)
    if sample.empty:
        dash = pd.DataFrame(columns=["player_no", "n_dash", "dash"])
    else:
        grouped = sample.groupby("player_no")["dash_residual"]
        dash = pd.DataFrame({
            "player_no": grouped.mean().index,
            "n_dash": grouped.size().to_numpy(),
            # 残差が負 = 同条件より序盤ロスが小さい = ダッシュ力あり → 符号反転
            "dash_raw": (-grouped.mean()).to_numpy(),
        })
        dash["dash"] = shrink(dash["dash_raw"], dash["n_dash"], k=k, center=0.0)

    per_player = st_stats.merge(dash, on="player_no", how="outer")
    if per_player.empty:
        per_player["start_score"] = np.nan
        return per_player, diagnostics

    # STは全体平均に向けて縮約(少数出走の極端な平均STを抑える)
    global_st = entries_df.loc[
        entries_df["status"] != settings.STATUS_SCRATCHED, "st"].dropna().mean()
    n_st = per_player["n_st"].fillna(0)
    per_player["st_shrunk"] = shrink(
        per_player["mean_st"].fillna(global_st), n_st, k=k, center=global_st)

    eligible = n_st >= min_races
    z_st = zscore((-per_player["st_shrunk"]).where(eligible))
    z_dash = zscore(per_player["dash"].where(eligible))
    # dash が無い選手はST側のみで代用(有効成分の平均)
    score = pd.concat([z_st, z_dash], axis=1).mean(axis=1)
    per_player["start_score"] = np.where(eligible, score, np.nan)
    return per_player, diagnostics


def expected_corner_order(race_entries: pd.DataFrame) -> pd.Series:
    """1レース分の出走行から想定1コーナー進入順(1始まり)を返す。

    (ハンデ昇順=前の位置ほど先, ST昇順=反応が速いほど先, 試走タイム昇順) の
    辞書式ソート順位。欠測は最後尾扱い。
    """
    df = race_entries.copy()
    big = 9999.0
    key = list(zip(
        df["handicap"].fillna(big),
        df["st"].fillna(big),
        df["trial_time"].fillna(big),
    ))
    order = pd.Series(key, index=df.index).rank(method="first")
    return order.astype(int)
