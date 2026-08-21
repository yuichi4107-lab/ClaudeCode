# -*- coding: utf-8 -*-
"""JRA-VANデータ特徴量（調教・血統）の実験モジュール — model_v2のラッパー、本番無改変

追加特徴量:
  調教(hanro=坂路。jvdata.sqlite、target_date未満のみ参照):
    tr_days_since   最終追切からの日数（上限35・データ無しは35）
    tr_n14 / tr_n28 直近14日/28日の本数（乗り込み量）
    tr_last_f4z     直前追切の4Fタイム（同トレセン直近60日母集団でz化、速い=負）
    tr_best_f4z_28  直近28日のベスト4F（z）
    tr_last_f1z     直前追切の終い1F（z）
    tr_fast_n14     直近14日の強め本数（f4z < -1.0）
    tr_has7         直近7日に追切あり(0/1)
  血統(bloodテーブルがあれば自動有効。過去レース結果からtarget_date未満で集計):
    bl_sire_surf    父×馬場種別の複勝率（事前分布0.25・n+30平滑化）
    bl_sire_dist    父×距離帯(〜1400/1401-1999/2000〜)の複勝率（同平滑化）
    bl_damsire_surf 母父×馬場種別の複勝率（同平滑化）
    bl_sire_n       父の産駒出走数（log1p）

リーク防止: 全て train_date/ra.date < target_date。leak_check()で機械検証可能。
"""
import math
import os
import sqlite3
import sys
from datetime import date as _date, timedelta

sys.path.insert(0, "/opt/keiba-unified/jra/scripts")
import model_v2

# インポート時点の元ビルダーを捕捉しておく。
# 呼び出し側が model_v2.build_features_for_date を本モジュールの関数へ差し替えても
# 無限再帰しないため（2026-07-12のE2Eテストで検知したバグの修正）
_ORIG_BFF = model_v2.build_features_for_date

JV_DB = "/opt/keiba-unified/jra/data/jvdata.sqlite"
KEIBA_DB = None  # None=build時のconnをそのまま血統集計に使う

TRAIN_COLS = ["tr_days_since", "tr_n14", "tr_n28", "tr_last_f4z",
              "tr_best_f4z_28", "tr_last_f1z", "tr_fast_n14", "tr_has7"]
BLOOD_COLS = ["bl_sire_surf", "bl_sire_dist", "bl_damsire_surf", "bl_sire_n"]

_jv_conn = None
_HAS_BLOOD = None
_TRESEN_STATS = {}   # (target_ymd, tresen) -> (mean_f4, std_f4, mean_f1, std_f1)
_SIRE_STATS = {}     # target_date -> dict


def _jv():
    global _jv_conn, _HAS_BLOOD
    if _jv_conn is None:
        _jv_conn = sqlite3.connect(f"file:{JV_DB}?mode=ro", uri=True)
        _HAS_BLOOD = bool(_jv_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='blood'").fetchone())
    return _jv_conn


def has_blood():
    _jv()
    return _HAS_BLOOD


FEATURE_COLS_NO_ODDS = list(model_v2.FEATURE_COLS_NO_ODDS) + TRAIN_COLS
FEATURE_COLS_FULL = list(model_v2.FEATURE_COLS_FULL) + TRAIN_COLS
# 血統列はbloodテーブルがある環境でのみ実験側が明示的に足す
FEATURE_COLS_NO_ODDS_B = FEATURE_COLS_NO_ODDS + BLOOD_COLS
FEATURE_COLS_FULL_B = FEATURE_COLS_FULL + BLOOD_COLS


def _ymd(target_date):
    return target_date.replace("-", "")


def _minus_days(target_date, days):
    y, m, d = int(target_date[:4]), int(target_date[5:7]), int(target_date[8:10])
    return (_date(y, m, d) - timedelta(days=days)).strftime("%Y%m%d")


def _tresen_stats(target_date, source, tresen):
    """坂路(hanro)/ウッド(wood)は時計水準が違うため (source, トレセン) 別に正規化"""
    key = (_ymd(target_date), source, tresen)
    if key in _TRESEN_STATS:
        return _TRESEN_STATS[key]
    c = _jv().cursor()
    row = c.execute(
        f"""SELECT AVG(f4), AVG(f4*f4), AVG(f1), AVG(f1*f1), COUNT(*)
           FROM {source} WHERE tresen = ? AND train_date < ? AND train_date >= ?
             AND f4 IS NOT NULL AND f1 IS NOT NULL""",
        (tresen, _ymd(target_date), _minus_days(target_date, 60))).fetchone()
    if not row or not row[4] or row[4] < 200:
        out = (54.0, 3.0, 13.5, 0.9) if source == "hanro" else (53.0, 2.5, 12.5, 0.8)
    else:
        m4, m4sq, m1, m1sq, _n = row
        s4 = math.sqrt(max(m4sq - m4 * m4, 0.01))
        s1 = math.sqrt(max(m1sq - m1 * m1, 0.01))
        out = (m4, s4, m1, s1)
    _TRESEN_STATS[key] = out
    return out


def _train_feats(horse_id, target_date):
    c = _jv().cursor()
    rows = []
    for source in ("hanro", "wood"):
        for tdate, ttime, tresen, f4, f1 in c.execute(
                f"""SELECT train_date, train_time, tresen, f4, f1 FROM {source}
                   WHERE horse_id = ? AND train_date < ? AND train_date >= ?""",
                (horse_id, _ymd(target_date), _minus_days(target_date, 35))):
            rows.append((tdate, ttime, source, tresen, f4, f1))
    rows.sort(key=lambda r: (r[0], r[1]), reverse=True)
    rows = [(r[0], (r[2], r[3]), r[4], r[5]) for r in rows]  # (date, (source,tresen), f4, f1)
    f = dict(tr_days_since=35.0, tr_n14=0, tr_n28=0, tr_last_f4z=0.0,
             tr_best_f4z_28=0.0, tr_last_f1z=0.0, tr_fast_n14=0, tr_has7=0)
    if not rows:
        return f
    ymd_t = _ymd(target_date)
    d14 = _minus_days(target_date, 14)
    d7 = _minus_days(target_date, 7)

    def days_between(a, b):
        da = _date(int(a[:4]), int(a[4:6]), int(a[6:8]))
        db_ = _date(int(b[:4]), int(b[4:6]), int(b[6:8]))
        return (db_ - da).days

    last = rows[0]
    f["tr_days_since"] = float(min(days_between(last[0], ymd_t), 35))
    f["tr_n28"] = len(rows)
    f["tr_n14"] = sum(1 for r in rows if r[0] >= d14)
    f["tr_has7"] = 1 if rows[0][0] >= d7 else 0

    z4s = []
    for tdate, st, f4, f1 in rows:
        if f4 is None:
            z4s.append(None)
            continue
        source, tresen = st
        m4, s4, m1, s1 = _tresen_stats(target_date, source, tresen if tresen is not None else 0)
        z4s.append((f4 - m4) / s4)
    if last[2] is not None:
        source, tresen = last[1]
        m4, s4, m1, s1 = _tresen_stats(target_date, source, tresen if tresen is not None else 0)
        f["tr_last_f4z"] = (last[2] - m4) / s4
        if last[3] is not None:
            f["tr_last_f1z"] = (last[3] - m1) / s1
    valid = [z for z in z4s if z is not None]
    if valid:
        f["tr_best_f4z_28"] = min(valid)
    f["tr_fast_n14"] = sum(1 for z, r in zip(z4s, rows) if z is not None and z < -1.0 and r[0] >= d14)
    return f


def _sire_stats(conn, target_date):
    """レース結果DB(conn)×bloodで、target_date未満の父/母父別成績を集計（日付ごとにキャッシュ）"""
    if target_date in _SIRE_STATS:
        return _SIRE_STATS[target_date]
    jc = _jv().cursor()
    blood = {}
    # 集計キーは繁殖登録番号(ID)。馬名は若い世代でカバレッジが低い(52-74%)がIDはほぼ100%
    for hid, sire, damsire in jc.execute("SELECT horse_id, sire_id, damsire_id FROM blood"):
        blood[hid] = (sire or "", damsire or "")
    c = conn.cursor()
    sire_surf = {}
    sire_dist = {}
    dams_surf = {}
    sire_n = {}
    for hid, surf, dist, fin in c.execute(
            """SELECT r.horse_id, ra.surface, ra.distance, r.finish_position
               FROM results r JOIN races ra ON ra.race_id = r.race_id
               WHERE ra.date < ? AND ra.date >= '2021-01-01' AND r.finish_position > 0""",
            (target_date,)):
        b = blood.get(hid)
        if not b:
            continue
        sire, dams = b
        top3 = 1 if fin <= 3 else 0
        band = 0 if (dist or 0) <= 1400 else (1 if (dist or 0) < 2000 else 2)
        if sire:
            k = (sire, surf)
            a = sire_surf.setdefault(k, [0, 0]); a[0] += top3; a[1] += 1
            k2 = (sire, band)
            a2 = sire_dist.setdefault(k2, [0, 0]); a2[0] += top3; a2[1] += 1
            sire_n[sire] = sire_n.get(sire, 0) + 1
        if dams:
            k3 = (dams, surf)
            a3 = dams_surf.setdefault(k3, [0, 0]); a3[0] += top3; a3[1] += 1
    out = dict(blood=blood, sire_surf=sire_surf, sire_dist=sire_dist,
               dams_surf=dams_surf, sire_n=sire_n)
    _SIRE_STATS.clear()          # 日付が進むと古いキャッシュは不要（メモリ節約）
    _SIRE_STATS[target_date] = out
    return out


def _blood_feats(st, horse_id, surface, distance):
    PRIOR, PN = 0.25, 30
    f = dict(bl_sire_surf=PRIOR, bl_sire_dist=PRIOR, bl_damsire_surf=PRIOR, bl_sire_n=0.0)
    b = st["blood"].get(horse_id)
    if not b:
        return f
    sire, dams = b
    band = 0 if (distance or 0) <= 1400 else (1 if (distance or 0) < 2000 else 2)
    if sire:
        a = st["sire_surf"].get((sire, surface))
        if a:
            f["bl_sire_surf"] = (a[0] + PRIOR * PN) / (a[1] + PN)
        a2 = st["sire_dist"].get((sire, band))
        if a2:
            f["bl_sire_dist"] = (a2[0] + PRIOR * PN) / (a2[1] + PN)
        f["bl_sire_n"] = math.log1p(st["sire_n"].get(sire, 0))
    if dams:
        a3 = st["dams_surf"].get((dams, surface))
        if a3:
            f["bl_damsire_surf"] = (a3[0] + PRIOR * PN) / (a3[1] + PN)
    return f


def build_features_for_date(conn, target_date):
    """model_v2の特徴量に調教（＋bloodがあれば血統）列を後付けする"""
    df = _ORIG_BFF(conn, target_date)
    if df is None or df.empty:
        return df
    df = df.copy()
    feats = [_train_feats(h, target_date) for h in df["horse_id"]]
    for col in TRAIN_COLS:
        df[col] = [f[col] for f in feats]
    if has_blood():
        st = _sire_stats(conn, target_date)
        surfaces = df["surface_turf"].map({1: "芝", 0: "ダート"})
        bl = [_blood_feats(st, h, s, d) for h, s, d in
              zip(df["horse_id"], surfaces, df["distance"])]
        for col in BLOOD_COLS:
            df[col] = [b[col] for b in bl]
    return df


def leak_check(keiba_db, sample_dates):
    """target_date以降のhanro/resultsを削除したコピーで特徴量が不変か機械検証"""
    import shutil
    import tempfile
    import pandas as pd
    global _jv_conn, _HAS_BLOOD, JV_DB
    ok = True
    for d in sample_dates:
        conn = sqlite3.connect(f"file:{keiba_db}?mode=ro", uri=True)
        _TRESEN_STATS.clear(); _SIRE_STATS.clear()
        df1 = build_features_for_date(conn, d)
        conn.close()

        tmp_jv = tempfile.mktemp(suffix=".db")
        shutil.copy(JV_DB.replace("file:", ""), tmp_jv) if JV_DB.startswith("file:") else shutil.copy(JV_DB, tmp_jv)
        cj = sqlite3.connect(tmp_jv)
        cj.execute("DELETE FROM hanro WHERE train_date >= ?", (_ymd(d),))
        try:
            cj.execute("DELETE FROM wood WHERE train_date >= ?", (_ymd(d),))
        except sqlite3.OperationalError:
            pass
        cj.commit(); cj.close()
        tmp_k = tempfile.mktemp(suffix=".db")
        shutil.copy(keiba_db, tmp_k)
        ck = sqlite3.connect(tmp_k)
        ck.execute("DELETE FROM results WHERE race_id IN (SELECT race_id FROM races WHERE date > ?)", (d,))
        ck.execute("DELETE FROM races WHERE date > ?", (d,))
        ck.commit(); ck.close()

        old_db, old_conn, old_has = JV_DB, _jv_conn, _HAS_BLOOD
        JV_DB, _jv_conn, _HAS_BLOOD = tmp_jv, None, None
        _TRESEN_STATS.clear(); _SIRE_STATS.clear()
        conn2 = sqlite3.connect(f"file:{tmp_k}?mode=ro", uri=True)
        df2 = build_features_for_date(conn2, d)
        conn2.close()
        JV_DB, _jv_conn, _HAS_BLOOD = old_db, old_conn, old_has
        os.remove(tmp_jv); os.remove(tmp_k)

        cols = TRAIN_COLS + (BLOOD_COLS if has_blood() else [])
        same = df1[cols].round(9).equals(df2[cols].round(9))
        print(f"leak-check {d}: {'OK' if same else 'NG'} rows={len(df1)}")
        if not same:
            ok = False
            diff = (df1[cols].round(9) != df2[cols].round(9)).sum()
            print(diff[diff > 0])
    print("LEAK CHECK", "PASSED" if ok else "FAILED")
    return ok


if __name__ == "__main__":
    if "--leak-check" in sys.argv:
        args = [a for a in sys.argv[1:] if a != "--leak-check"]
        sys.exit(0 if leak_check(args[0], args[1:] or ["2026-06-01"]) else 1)
