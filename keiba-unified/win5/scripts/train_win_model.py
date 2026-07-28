"""較正済み1着確率モデルを学習し、OOSで人気ベースラインと比較する。

単一parquet（特徴量+target+メタ）を --cutoff で時系列分割し、
train で 較正モデル と 人気ベースライン を学習、OOS で両者を比較する。

合格条件(spec §6/§7 P2): OOSで モデルが ベースライン を Brier・LogLoss で下回り、
かつ race-level top1_hit_rate で上回ること。満たさなければ「ベースライン採用/撤退」を明示。

使い方:
  PYTHONPATH=src python scripts/train_win_model.py \
      --data /c/dev/win5_tmp/features_all.parquet --cutoff 2025-01-01
"""

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from model.calibration import CalibratedWinModel  # noqa: E402
from model.evaluation import compute_metrics, compute_race_level_metrics  # noqa: E402
from model.oos_split import time_split  # noqa: E402
from model.popularity_baseline import PopularityBaseline  # noqa: E402


def _feature_cols(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if not c.startswith("_") and c != "target"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="/c/dev/win5_tmp/features_all.parquet")
    ap.add_argument("--cutoff", default="2025-01-01")
    args = ap.parse_args()

    df = pd.read_parquet(args.data)
    train, oos = time_split(df, cutoff=args.cutoff, date_col="_race_date")
    feats = _feature_cols(df)

    print(f"data={len(df)} train={len(train)} oos={len(oos)} features={len(feats)}")
    print(f"train positive_rate={train['target'].mean():.4f} oos positive_rate={oos['target'].mean():.4f}")
    if len(train) == 0 or len(oos) == 0:
        print("RESULT: SKIP — train か oos が空。cutoff/データ範囲を確認。")
        return

    # --- 較正済みモデル ---
    model = CalibratedWinModel(method="isotonic").fit(train, feature_cols=feats)
    oos_model_p = model.predict_proba(oos, feature_cols=feats)

    # --- 人気ベースライン ---
    baseline = PopularityBaseline().fit(train)
    oos_base_p = baseline.predict(oos)

    y = oos["target"].values
    m = compute_metrics(y, oos_model_p)
    b = compute_metrics(y, oos_base_p)

    oos_m = oos.copy(); oos_m["_pred"] = oos_model_p
    oos_b = oos.copy(); oos_b["_pred"] = oos_base_p
    mr = compute_race_level_metrics(oos_m, prob_col="_pred")
    br = compute_race_level_metrics(oos_b, prob_col="_pred")

    print("=== OOS comparison (model vs popularity baseline) ===")
    print(f"Brier   model={m['brier']:.5f}  baseline={b['brier']:.5f}  (lower is better)")
    print(f"LogLoss model={m['logloss']:.5f}  baseline={b['logloss']:.5f}  (lower is better)")
    print(f"AUC     model={m['auc']:.4f}  baseline={b['auc']:.4f}")
    print(f"top1hit model={mr['top1_hit_rate']:.4f}  baseline={br['top1_hit_rate']:.4f}")

    beats = (
        m["brier"] < b["brier"]
        and m["logloss"] < b["logloss"]
        and mr["top1_hit_rate"] >= br["top1_hit_rate"]
    )
    if beats:
        print("RESULT: PASS - model beats popularity baseline on OOS. 採用候補。P3(買い目最適化+バックテスト)へ。")
    else:
        print("RESULT: FAIL - model does NOT clearly beat baseline. "
              "正直な結論: ベースライン採用 or WIN5は実弾時期尚早を検討(spec 6)。")


if __name__ == "__main__":
    main()
