# -*- coding: utf-8 -*-
"""四半期 自動再学習パイプライン（cron: 1,4,7,10月の2日 01:00 想定）

「学習窓が2024年末で止まったまま半年運用されていた」(2026-07-05検証で判明)
の再発防止。手順は同日の手動バージョンアップと同一プロトコル:

  1. 本番DBを/tmpへ整合コピー（sqlite backup API）＋インデックス付与
  2. 特徴量を一括並列ビルド（学習・OOS評価で共有）
  3. 候補モデルを「OOS窓（直近約13週）を除外した窓」で学習
  4. 本番モデル vs 候補を OOS窓・実払戻・本番構成で対決
     - 朝C5b: generate_bets_c5b + evaluate_race_quality_no_odds @ 0.92
     - ライブ: generate_bets + evaluate_race_quality @ 0.86
  5. 候補が「ROIで上回り、かつ的中率が1pt超劣化しない」場合のみ、
     全量窓で最終モデルを学習し、バックアップを取って差し替え
  6. 結果は常にTelegramへ報告（差し替え有無・数値・revertコマンド）

安全装置:
  - AUTO_SWAP=0 で判定のみ（差し替えせず報告）
  - SMOKE=1 でスモークテスト（縮小データ・差し替えなし）
  - 差し替え前に必ず .bak.YYYYMMDD_autoretrain を作成
"""
import os
import sys
import time
import json
import shutil
import sqlite3
from datetime import date, timedelta

JRA_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(JRA_DIR, "scripts"))
os.chdir(JRA_DIR)

DB_PROD = os.path.join(JRA_DIR, "data", "keiba_live.db")
DB_WORK = "/tmp/auto_retrain.db"
FEATS_CACHE = "/tmp/auto_retrain_feats.pkl"
MODELS = os.path.join(JRA_DIR, "data", "models")

TRAIN_START = "2022-01-01"
OOS_DAYS = 91           # 直近約13週をOOS窓に
MORNING_T = 0.92        # run_morning.py C5B_MORNING_THRESHOLD と揃える
LIVE_T = 0.86           # predictor_v1.QUALITY_THRESHOLD と揃える
MIN_OOS_RACES = 60      # 現行・候補ともこれ未満なら判定保留（据え置き）
SWAP_MARGIN = 3.0       # ROIがこのpt以上、上回った場合のみ差し替え（ノイズ差替の防止）
SMOKE = os.environ.get("SMOKE") == "1"
AUTO_SWAP = os.environ.get("AUTO_SWAP", "1") == "1" and not SMOKE

TRACKS = [
    dict(key="morning_c5b", label="朝C5b(オッズ抜き)",
         prod_model=os.path.join(MODELS, "model_v2_no_odds.pkl"),
         cols="NO_ODDS", threshold=MORNING_T,
         cand="/tmp/auto_cand_no_odds.pkl",
         final="/tmp/auto_final_no_odds.pkl"),
    dict(key="live_full", label="ライブFULL",
         prod_model=os.path.join(MODELS, "model_v2_live.pkl"),
         cols="FULL", threshold=LIVE_T,
         cand="/tmp/auto_cand_full.pkl",
         final="/tmp/auto_final_full.pkl"),
]


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def copy_db():
    src = sqlite3.connect(f"file:{DB_PROD}?mode=ro", uri=True)
    if os.path.exists(DB_WORK):
        os.remove(DB_WORK)
    dst = sqlite3.connect(DB_WORK)
    src.backup(dst)
    for ix in ["CREATE INDEX IF NOT EXISTS idx_results_horse ON results(horse_id)",
               "CREATE INDEX IF NOT EXISTS idx_results_jockey ON results(jockey_id)",
               "CREATE INDEX IF NOT EXISTS idx_results_trainer ON results(trainer_id)",
               "CREATE INDEX IF NOT EXISTS idx_results_race ON results(race_id)",
               "CREATE INDEX IF NOT EXISTS idx_races_date ON races(date)"]:
        dst.execute(ix)
    dst.commit()
    dst.close()
    src.close()
    log("DBコピー完了")


def _build_one(d):
    import model_v2
    conn = sqlite3.connect(DB_WORK)
    try:
        df = model_v2.build_features_for_date(conn, d)
        if df is not None and not df.empty:
            df = df.copy()
            df["date"] = d
        return (d, df)
    finally:
        conn.close()


def build_features(end_date):
    import pandas as pd
    from multiprocessing import Pool
    conn = sqlite3.connect(DB_WORK)
    dates = [r[0] for r in conn.execute(
        "SELECT DISTINCT date FROM races WHERE date BETWEEN ? AND ? "
        "AND surface IN ('芝','ダート') ORDER BY date", (TRAIN_START, end_date))]
    conn.close()
    if SMOKE:
        dates = dates[-90:]
        log(f"[SMOKE] 直近{len(dates)}日に縮小")
    log(f"特徴量ビルド開始: {len(dates)}日分")
    t = time.time()
    with Pool(3) as p:
        pairs = p.map(_build_one, dates)
    per_date = {d: df for d, df in pairs if df is not None and not df.empty}
    df = pd.concat(list(per_date.values()), ignore_index=True)
    df.to_pickle(FEATS_CACHE)
    log(f"特徴量ビルド完了: {time.time()-t:.0f}s rows={len(df)}")
    return df, per_date


def train(df, cols_name, end_date, out_path):
    import model_v2
    cols = model_v2.FEATURE_COLS_NO_ODDS if cols_name == "NO_ODDS" else model_v2.FEATURE_COLS_FULL
    sub = df[df["date"] <= end_date]
    log(f"学習 {cols_name} <= {end_date}: rows={len(sub)} -> {out_path}")
    model_v2.FEATURE_COLS = cols
    model_v2.MODEL_PATH = out_path
    model_v2.build_training_data = lambda c, s, e, _sub=sub: _sub
    conn = sqlite3.connect(DB_WORK)
    model_v2.train_model(conn, TRAIN_START, end_date)
    conn.close()


def evaluate(track, model_path, oos_dates, feat_cache):
    """OOS窓で本番構成のROI/的中率を計測（実払戻・flat=本番配分）"""
    import model_v2
    import predictor_v1
    cols = model_v2.FEATURE_COLS_NO_ODDS if track["cols"] == "NO_ODDS" else model_v2.FEATURE_COLS_FULL
    model_v2.MODEL_PATH = model_path
    model_v2.FEATURE_COLS = cols
    model_v2.build_features_for_date = lambda c, d: feat_cache.get(d)

    qs_map = {}
    base_q = (predictor_v1.evaluate_race_quality_no_odds if track["cols"] == "NO_ODDS"
              else _ORIG_QUAL)

    def qwrap(c, rid, scored, race_info=None):
        q = base_q(c, rid, scored, race_info)
        qs_map[rid] = q.get("quality_score", 0.0)
        return q

    predictor_v1.QUALITY_THRESHOLD = 0.0
    predictor_v1.evaluate_race_quality = qwrap
    gen = (predictor_v1.generate_bets_c5b if track["cols"] == "NO_ODDS"
           else _ORIG_GEN)

    conn = sqlite3.connect(DB_WORK)
    cur = conn.cursor()
    inv = pay = hits = races = 0
    for d in oos_dates:
        if d not in feat_cache:
            continue
        try:
            evs = predictor_v1.select_races(conn, d)
        except Exception as e:
            log(f"  eval fail {d}: {e}")
            continue
        for ev in evs:
            rid = ev["race_id"]
            if qs_map.get(rid, 0.0) < track["threshold"]:
                continue
            n_fin = cur.execute("SELECT COUNT(*) FROM results WHERE race_id=? AND finish_position>0",
                                (rid,)).fetchone()[0]
            if n_fin < 3:
                continue
            bets = gen(ev["scored_horses"], ev.get("race_info") or {}, 5000)
            bt = bets.get("bet_type")
            if bt not in ("三連複", "馬連") or not bets.get("bets"):
                continue
            pm = {}
            for b_bt, comb, po in cur.execute(
                    "SELECT bet_type,combination,payout FROM payouts WHERE race_id=?", (rid,)):
                try:
                    pm[(b_bt, tuple(sorted(int(x) for x in comb.replace("→", " ").replace("-", " ").split())))] = po
                except ValueError:
                    continue
            r_inv = r_pay = 0
            for b in bets["bets"]:
                try:
                    key = (bt, tuple(sorted(int(x) for x in b["combination"].replace(" ", "").split("-"))))
                    amt = int(b.get("amount", 0) or 0)
                except (ValueError, TypeError):
                    continue
                r_inv += amt
                po = pm.get(key)
                if po:
                    r_pay += po * amt // 100
            if r_inv <= 0:
                continue
            races += 1
            inv += r_inv
            pay += r_pay
            if r_pay > 0:
                hits += 1
    conn.close()
    roi = 100.0 * pay / inv if inv else 0.0
    hr = 100.0 * hits / races if races else 0.0
    return dict(races=races, hits=hits, inv=inv, pay=pay, roi=roi, hit_rate=hr)


def _validate_model_file(path):
    """差し替え前の最終モデル健全性検証: pickleロード可能＋必須キー存在"""
    import pickle
    with open(path, "rb") as f:
        d = pickle.load(f)
    if not (isinstance(d, dict) and "model" in d and "feature_cols" in d):
        raise RuntimeError(f"モデルファイル構造が不正: {path}")


def swap_model(prod_model, final_path, stamp):
    """最終モデルを本番パスへ差し替える（必ずバックアップを先に作る）。

    戻り値: バックアップファイルのパス。--test-swap でこの経路単体を
    ダミーファイルでリハーサルできる。
    """
    backup = prod_model + f".bak.{stamp}_autoretrain"
    shutil.copy2(prod_model, backup)
    shutil.copy2(final_path, prod_model)
    # 差し替え結果の健全性確認: サイズ一致＋読める
    if os.path.getsize(prod_model) != os.path.getsize(final_path):
        shutil.copy2(backup, prod_model)
        raise RuntimeError("swap後のサイズ不一致を検出したためrevertした")
    return backup


def _test_swap():
    """差し替え経路のリハーサル（ダミーファイルで copy→backup→上書き→revert を実走）"""
    import tempfile
    d = tempfile.mkdtemp(prefix="swap_test_")
    prod = os.path.join(d, "prod.pkl")
    final = os.path.join(d, "final.pkl")
    open(prod, "w").write("OLD MODEL")
    open(final, "w").write("NEW MODEL!")
    backup = swap_model(prod, final, "TEST")
    assert open(prod).read() == "NEW MODEL!", "差し替え失敗"
    assert open(backup).read() == "OLD MODEL", "バックアップ不正"
    shutil.copy2(backup, prod)  # revert
    assert open(prod).read() == "OLD MODEL", "revert失敗"
    shutil.rmtree(d)
    print("swap rehearsal OK: copy→backup→上書き→revert の全経路が動作")


def notify(msg):
    try:
        from check_results import send_telegram
        send_telegram(msg)
    except Exception as e:
        log(f"Telegram送信失敗: {e}")


def main():
    global _ORIG_QUAL, _ORIG_GEN
    import predictor_v1
    _ORIG_QUAL = predictor_v1.evaluate_race_quality
    _ORIG_GEN = predictor_v1.generate_bets

    today = date.today()
    end_all = (today - timedelta(days=1)).strftime("%Y-%m-%d")
    oos_start = (today - timedelta(days=OOS_DAYS)).strftime("%Y-%m-%d")
    cand_end = (today - timedelta(days=OOS_DAYS + 1)).strftime("%Y-%m-%d")
    log(f"=== auto_retrain {today} | 候補学習<= {cand_end} | OOS {oos_start}..{end_all} | "
        f"AUTO_SWAP={AUTO_SWAP} SMOKE={SMOKE} ===")

    copy_db()
    df, feat_cache = build_features(end_all)

    conn = sqlite3.connect(DB_WORK)
    oos_dates = [r[0] for r in conn.execute(
        "SELECT DISTINCT date FROM races WHERE date BETWEEN ? AND ? ORDER BY date",
        (oos_start, end_all))]
    conn.close()

    lines = [f"🔁 *JRA 四半期自動再学習 {today}*", f"OOS窓: {oos_start}〜{end_all}"]
    for track in TRACKS:
        log(f"--- {track['label']} ---")
        train(df, track["cols"], cand_end, track["cand"])
        prod = evaluate(track, track["prod_model"], oos_dates, feat_cache)
        cand = evaluate(track, track["cand"], oos_dates, feat_cache)
        log(f"prod: {prod} / cand: {cand}")
        line = (f"\n*{track['label']}* (n={prod['races']}R@{track['threshold']})\n"
                f"  現行: ROI {prod['roi']:.1f}% / 的中 {prod['hit_rate']:.1f}%\n"
                f"  候補: ROI {cand['roi']:.1f}% / 的中 {cand['hit_rate']:.1f}%")
        win = (prod["races"] >= MIN_OOS_RACES
               and cand["races"] >= MIN_OOS_RACES
               and cand["roi"] > prod["roi"] + SWAP_MARGIN
               and cand["hit_rate"] >= prod["hit_rate"] - 1.0)
        if win and AUTO_SWAP:
            train(df, track["cols"], end_all, track["final"])
            _validate_model_file(track["final"])
            backup = swap_model(track["prod_model"], track["final"], today.strftime("%Y%m%d"))
            line += (f"\n  → ✅ 差し替え実施（学習<= {end_all}）\n"
                     f"  revert: cp {os.path.basename(backup)} {os.path.basename(track['prod_model'])}")
            log(f"SWAPPED {track['key']} (backup={backup})")
        elif win:
            line += "\n  → 候補優位（AUTO_SWAP無効のため据え置き・手動で差し替え判断を）"
        else:
            if prod["races"] < MIN_OOS_RACES or cand["races"] < MIN_OOS_RACES:
                reason = "OOSレース不足"
            elif cand["roi"] > prod["roi"]:
                reason = f"改善幅がマージン{SWAP_MARGIN:.0f}pt未満"
            else:
                reason = "候補が現行を上回らず"
            line += f"\n  → 据え置き（{reason}）"
        lines.append(line)

    msg = "\n".join(lines)
    print("\n" + msg)
    if not SMOKE:
        notify(msg)
    log("AUTO_RETRAIN DONE")


if __name__ == "__main__":
    if "--test-swap" in sys.argv:
        _test_swap()
    else:
        main()
