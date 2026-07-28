# WIN5 Win-Probability Model (P2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 移植済みJRAデータ（win5.db, 2021-2026）で「各馬の1着確率」を予測する較正済みモデルを学習し、学習期間外（OOS）で**人気ベースラインを上回るか**を厳密に検証する。上回らなければ「機械学習不要／撤退」を正直な結論として出す。

**Architecture:** 既存の `FeatureBuilder.build_training_data`（特徴量＋target=1着）と `LightGBMTrainer`/`evaluation` を土台に、不足している3点を追加する: (1) 確率較正（CalibratedClassifierCV）, (2) 時系列OOS分割, (3) 人気ベースライン（OneDrive `popularity/PopularityModel`=P(win|人気)）との比較。学習は全JRAレースで行い、評価はOOS期間（既定: train≤2024-12-31 / test=2025）。

**Tech Stack:** Python 3.12, LightGBM, scikit-learn（CalibratedClassifierCV / metrics）, pandas, pytest。win5.db(SQLite)。

**実行前提:** `keiba-unified/win5/` をカレント、`PYTHONPATH=src`。ブランチ `feat/win5-data-foundation` を継続（push禁止、`git add` は win5 配下のみ）。win5.db は P0/P1 完了済み（17,457レース/240,330着順/win5_events 326）。

**真実源（計画コードと食い違えば実コードに合わせる）:**
- `src/features/builder.py`: `FeatureBuilder(repo).build_training_data(start, end, include_odds=True) -> DataFrame`（列: 特徴量 + `target`(1着=1) + メタ `_race_id`/`_horse_id`/`_race_date`/`_finish_position`）。`get_feature_names()`。
- `src/model/trainer.py`: `LightGBMTrainer().train(df, feature_cols=None, target_col="target") -> LGBMClassifier`。`self.model.predict_proba(X)`。`_get_feature_cols(df, target_col)`（メタ`_*`とtarget除外）。`save/load`。
- `src/model/evaluation.py`: `compute_metrics(y_true, y_pred_proba) -> {auc,logloss,brier,accuracy,precision,recall}`。`compute_race_level_metrics(df, pred_col, actual_col="_finish_position") -> {top1_hit_rate,top3_hit_rate,avg_winner_rank}`。
- `src/model/registry.py`: モデル登録（既存）。
- OneDrive `src/popularity/model.py`: `PopularityModel(max_rank=18).fit(list[int 人気]).win_prob(rank)->float`（= P(1着馬がk番人気)）。

---

## File Structure

新規/取込:
- `src/popularity/`（OneDriveから取込・P2.0）: `__init__.py` `model.py` `loader.py` 他
- `src/model/oos_split.py` — 時系列OOS分割（純粋関数）
- `src/model/popularity_baseline.py` — `PopularityBaseline`（P(win|人気)を各馬に付与）
- `src/model/calibration.py` — `CalibratedWinModel`（LightGBM + 確率較正ラッパ）
- `scripts/build_training_data.py` — win5.db → 特徴量DataFrame を parquet 保存（スモーク→本番）
- `scripts/train_win_model.py` — OOS学習・評価・ベースライン比較・登録（統合・合格ゲート）
- `tests/test_model/__init__.py`
- `tests/test_model/test_oos_split.py`
- `tests/test_model/test_popularity_baseline.py`
- `tests/test_model/test_calibration.py`

データ生成物（gitignore対象・コミットしない）:
- `data/features_train.parquet` / `data/features_oos.parquet`
- `models/win_model_*.joblib`

---

## Task 0: popularity パッケージの取込（P2前提）

**Files:**
- Create: `src/popularity/*`（OneDriveからコピー）

- [ ] **Step 1: OneDriveから popularity パッケージをコピー**

Run:
```bash
cd "g:/マイドライブ/YNFactory-cc/keiba-unified/win5"
cp -r "C:/Users/fcmdt/OneDrive/デスクトップ/ClaudeCode-claude-win-prediction-model-Izfwm/ClaudeCode-claude-win-prediction-model-Izfwm/win5_predictor/src/popularity" src/popularity
```
Expected: `src/popularity/__init__.py` `model.py` `loader.py` 等がコピーされる。

- [ ] **Step 2: import 疎通確認**

Run:
```bash
PYTHONPATH=src python -c "from popularity.model import PopularityModel; m=PopularityModel().fit([1,1,2,3,1,2]); print('win_prob(1)=', round(m.win_prob(1),3)); print('OK')"
```
Expected: `win_prob(1)=0.5`（6戦中3勝が1番人気）と `OK`。import エラーが出たら、相対import（`from .odds import ...` 等）を `src` 直下namespaceに合わせて修正（`from popularity.odds import ...`）。

- [ ] **Step 3: Commit**

```bash
git add src/popularity
git commit -m "chore(win5): import popularity package from onedrive (P2 baseline)"
```

---

## Task 1: 時系列OOS分割（oos_split.py）

**Files:**
- Create: `src/model/oos_split.py`
- Test: `tests/test_model/__init__.py`, `tests/test_model/test_oos_split.py`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_model/__init__.py`:
```python
```

`tests/test_model/test_oos_split.py`:
```python
import pandas as pd

from model.oos_split import time_split


def test_time_split_by_cutoff():
    df = pd.DataFrame(
        {
            "_race_date": ["2024-12-30", "2025-01-05", "2024-06-01", "2025-12-28"],
            "target": [1.0, 0.0, 1.0, 0.0],
        }
    )
    train, test = time_split(df, cutoff="2025-01-01", date_col="_race_date")
    assert sorted(train["_race_date"]) == ["2024-06-01", "2024-12-30"]
    assert sorted(test["_race_date"]) == ["2025-01-05", "2025-12-28"]


def test_time_split_empty_test_when_cutoff_future():
    df = pd.DataFrame({"_race_date": ["2024-01-01"], "target": [1.0]})
    train, test = time_split(df, cutoff="2030-01-01", date_col="_race_date")
    assert len(train) == 1
    assert len(test) == 0
```

- [ ] **Step 2: 失敗確認**

Run: `python -m pytest tests/test_model/test_oos_split.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'model.oos_split'`）

- [ ] **Step 3: 実装**

`src/model/oos_split.py`:
```python
"""時系列のOOS（学習期間外）分割。未来リーク防止のため日付で厳密に分ける。"""

import pandas as pd


def time_split(df: pd.DataFrame, cutoff: str, date_col: str = "_race_date"):
    """cutoff 未満を train、cutoff 以降を test として返す。

    Returns: (train_df, test_df)
    """
    dates = pd.to_datetime(df[date_col])
    cut = pd.to_datetime(cutoff)
    train = df[dates < cut].copy()
    test = df[dates >= cut].copy()
    return train, test
```

- [ ] **Step 4: 通過確認**

Run: `python -m pytest tests/test_model/test_oos_split.py -v`
Expected: PASS（2テスト）

- [ ] **Step 5: Commit**

```bash
git add src/model/oos_split.py tests/test_model/__init__.py tests/test_model/test_oos_split.py
git commit -m "feat(win5-model): add time-based OOS split"
```

---

## Task 2: 人気ベースライン（popularity_baseline.py）

**Files:**
- Create: `src/model/popularity_baseline.py`
- Test: `tests/test_model/test_popularity_baseline.py`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_model/test_popularity_baseline.py`:
```python
import numpy as np
import pandas as pd

from model.popularity_baseline import PopularityBaseline


def _train_df():
    # 4レース×各2頭。各レースの勝ち馬(target=1)の人気を変えて学習させる
    return pd.DataFrame(
        {
            "_race_id": ["r1", "r1", "r2", "r2", "r3", "r3", "r4", "r4"],
            "popularity": [1, 2, 1, 2, 1, 2, 2, 1],
            "target": [1.0, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 0.0],
        }
    )


def test_fit_and_predict_win_prob_by_popularity():
    bl = PopularityBaseline().fit(_train_df())
    # 学習: 1番人気が勝った回数=3/4=0.75、2番人気=1/4=0.25
    df = pd.DataFrame({"popularity": [1, 2]})
    probs = bl.predict(df)
    assert abs(probs[0] - 0.75) < 1e-6
    assert abs(probs[1] - 0.25) < 1e-6


def test_predict_unknown_rank_returns_small_prob():
    bl = PopularityBaseline().fit(_train_df())
    probs = bl.predict(pd.DataFrame({"popularity": [18]}))
    assert 0.0 <= probs[0] <= 1.0
```

- [ ] **Step 2: 失敗確認**

Run: `python -m pytest tests/test_model/test_popularity_baseline.py -v`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: 実装**

`src/model/popularity_baseline.py`:
```python
"""人気ベースライン: P(win | 人気順) を学習データから推定し各馬へ付与する。

機械学習モデルがOOSでこのベースラインを上回れるかが採用可否の判断基準。
内部で popularity.model.PopularityModel（1着馬がk番人気である確率）を使う。
"""

import numpy as np
import pandas as pd

from popularity.model import PopularityModel


class PopularityBaseline:
    def __init__(self, max_rank: int = 18):
        self.model = PopularityModel(max_rank=max_rank)

    def fit(self, train_df: pd.DataFrame, pop_col: str = "popularity",
            target_col: str = "target") -> "PopularityBaseline":
        winners = train_df[train_df[target_col] == 1.0]
        pops = [int(p) for p in winners[pop_col].dropna().tolist()]
        self.model.fit(pops)
        return self

    def predict(self, df: pd.DataFrame, pop_col: str = "popularity") -> np.ndarray:
        out = []
        for p in df[pop_col].tolist():
            if pd.isna(p):
                out.append(0.0)
            else:
                out.append(float(self.model.win_prob(int(p))))
        return np.asarray(out)
```

- [ ] **Step 4: 通過確認**

Run: `python -m pytest tests/test_model/test_popularity_baseline.py -v`
Expected: PASS

> もし `PopularityModel.win_prob` の正規化が異なり期待値0.75/0.25にならない場合、`model.py` の実装を確認し、`win_prob` が「P(1着馬がk番人気)」を返すことを前提にテスト期待値を実値へ合わせる（model.py が真実）。

- [ ] **Step 5: Commit**

```bash
git add src/model/popularity_baseline.py tests/test_model/test_popularity_baseline.py
git commit -m "feat(win5-model): add popularity baseline (P(win|rank))"
```

---

## Task 3: 確率較正ラッパ（calibration.py）

**Files:**
- Create: `src/model/calibration.py`
- Test: `tests/test_model/test_calibration.py`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_model/test_calibration.py`:
```python
import numpy as np
import pandas as pd

from model.calibration import CalibratedWinModel


def _toy(n=400):
    rng = np.random.RandomState(0)
    x = rng.rand(n)
    # 真の確率は x に単調。target をベルヌーイ生成
    p = x * 0.6
    y = (rng.rand(n) < p).astype(float)
    return pd.DataFrame({"f1": x, "target": y, "_race_date": ["2024-01-01"] * n})


def test_calibrated_probs_are_valid_and_predict_proba_shape():
    df = _toy()
    m = CalibratedWinModel(method="isotonic").fit(df, feature_cols=["f1"])
    probs = m.predict_proba(df, feature_cols=["f1"])
    assert probs.shape == (len(df),)
    assert float(probs.min()) >= 0.0
    assert float(probs.max()) <= 1.0


def test_calibration_does_not_worsen_brier_much_vs_raw():
    from sklearn.metrics import brier_score_loss

    df = _toy()
    m = CalibratedWinModel(method="isotonic").fit(df, feature_cols=["f1"])
    probs = m.predict_proba(df, feature_cols=["f1"])
    brier = brier_score_loss(df["target"].values, probs)
    # ベース率予測(全部平均)のBrierより良い
    base = brier_score_loss(df["target"].values, np.full(len(df), df["target"].mean()))
    assert brier <= base + 1e-9
```

- [ ] **Step 2: 失敗確認**

Run: `python -m pytest tests/test_model/test_calibration.py -v`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: 実装**

`src/model/calibration.py`:
```python
"""LightGBM(またはsklearn互換)分類器に確率較正を施すラッパ。

EVは較正後の勝率で計算する方針（spec §6）。学習時に内部CVで較正する。
"""

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV

try:
    from lightgbm import LGBMClassifier
    _BASE = LGBMClassifier
except Exception:  # pragma: no cover - fallback when lightgbm absent
    from sklearn.ensemble import HistGradientBoostingClassifier as _BASE

from config.settings import LIGHTGBM_DEFAULT_PARAMS


class CalibratedWinModel:
    def __init__(self, method: str = "isotonic", params: dict | None = None, cv: int = 3):
        self.method = method
        self.cv = cv
        try:
            self.params = params or LIGHTGBM_DEFAULT_PARAMS.copy()
        except Exception:
            self.params = params or {}
        self.feature_cols: list[str] = []
        self.calibrated: CalibratedClassifierCV | None = None

    def _matrix(self, df: pd.DataFrame, feature_cols: list[str]) -> np.ndarray:
        X = df[feature_cols].values.astype(np.float32)
        return np.nan_to_num(X, nan=0.0, posinf=1e6, neginf=-1e6)

    def fit(self, df: pd.DataFrame, feature_cols: list[str],
            target_col: str = "target") -> "CalibratedWinModel":
        self.feature_cols = feature_cols
        X = self._matrix(df, feature_cols)
        y = df[target_col].values.astype(int)
        try:
            base = _BASE(**self.params)
        except TypeError:
            base = _BASE()
        self.calibrated = CalibratedClassifierCV(base, method=self.method, cv=self.cv)
        self.calibrated.fit(X, y)
        return self

    def predict_proba(self, df: pd.DataFrame, feature_cols: list[str] | None = None) -> np.ndarray:
        cols = feature_cols or self.feature_cols
        X = self._matrix(df, cols)
        return self.calibrated.predict_proba(X)[:, 1]
```

- [ ] **Step 4: 通過確認**

Run: `python -m pytest tests/test_model/test_calibration.py -v`
Expected: PASS（lightgbm未導入でもHGBTフォールバックでPASS）

- [ ] **Step 5: Commit**

```bash
git add src/model/calibration.py tests/test_model/test_calibration.py
git commit -m "feat(win5-model): add probability-calibrated win model wrapper"
```

---

## Task 4: 学習データ生成（build_training_data.py）— スモーク優先

**Files:**
- Create: `scripts/build_training_data.py`

> 注意: `FeatureBuilder.build_training_data` は各馬で `get_horse_history` を引くため、240k件の本番生成は時間がかかる可能性。**必ず1か月でスモーク計測してから**全期間に進む。

- [ ] **Step 1: スクリプトを書く**

`scripts/build_training_data.py`:
```python
"""win5.db から特徴量データセットを生成し parquet 保存する。

使い方:
  PYTHONPATH=src python scripts/build_training_data.py --start 2021-01-01 --end 2024-12-31 --out data/features_train.parquet
"""

import argparse
import logging
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from database.connection import Database  # noqa: E402
from database.repository import Repository  # noqa: E402
from features.builder import FeatureBuilder  # noqa: E402


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--win5-db", default="data/win5.db")
    args = ap.parse_args()

    repo = Repository(Database(db_path=args.win5_db))
    fb = FeatureBuilder(repo)

    t0 = time.time()
    df = fb.build_training_data(date.fromisoformat(args.start), date.fromisoformat(args.end))
    dt = time.time() - t0

    if df.empty:
        print("NO DATA")
        return
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(args.out)
    print(f"DONE: rows={len(df)} cols={df.shape[1]} positive_rate={df['target'].mean():.3f} "
          f"elapsed={dt:.1f}s -> {args.out}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 1か月スモーク（性能計測）**

Run:
```bash
PYTHONPATH=src python scripts/build_training_data.py --start 2024-01-01 --end 2024-01-31 --out data/_smoke.parquet
```
Expected: `DONE: rows=数千 ... elapsed=N秒`。**elapsed から全期間(約36か月)を概算**。
- 概算が許容（例 全期間 < 30分）なら Step 3 へ。
- 遅すぎる場合は次のいずれかを実施してから Step 3:
  (a) win5.db をローカルSSD（例 `C:/dev/win5_build.db`）にコピーして `--win5-db` に指定（Drive read回避）、
  (b) それでも遅ければ学習期間を 2022-2024 に短縮、または race を間引かず horse_history 取得を軽量化（`build_for_entry` の履歴件数上限確認）。
  対応後に再計測し、採用した方針を記録。

- [ ] **Step 3: 本番生成（train期間とOOS期間を別ファイルに）**

Run:
```bash
PYTHONPATH=src python scripts/build_training_data.py --start 2021-01-01 --end 2024-12-31 --out data/features_train.parquet
PYTHONPATH=src python scripts/build_training_data.py --start 2025-01-01 --end 2025-12-31 --out data/features_oos.parquet
```
Expected: train は十万件規模 / oos は数万件規模、`positive_rate` は概ね 1/頭数（≈0.07前後）。

- [ ] **Step 4: features を gitignore に追加（コミットしない）**

`win5/.gitignore`（無ければ作成）に追記:
```
data/*.parquet
data/_smoke.parquet
```

- [ ] **Step 5: Commit（スクリプトとignoreのみ）**

```bash
git add scripts/build_training_data.py win5/.gitignore
git commit -m "feat(win5-model): add training-data builder script"
```

---

## Task 5: OOS学習・評価・ベースライン比較（train_win_model.py）

**Files:**
- Create: `scripts/train_win_model.py`

- [ ] **Step 1: スクリプトを書く**

`scripts/train_win_model.py`:
```python
"""較正済み1着確率モデルを学習し、OOSで人気ベースラインと比較する。

合格条件(spec §6/§7 P2): OOSで モデルが ベースライン を Brier・LogLoss で下回り、
かつ race-level top1_hit_rate で上回ること。満たさなければ「ベースライン採用/撤退」を明示。

使い方:
  PYTHONPATH=src python scripts/train_win_model.py \
      --train data/features_train.parquet --oos data/features_oos.parquet
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from model.calibration import CalibratedWinModel  # noqa: E402
from model.popularity_baseline import PopularityBaseline  # noqa: E402
from model.evaluation import compute_metrics, compute_race_level_metrics  # noqa: E402


def _feature_cols(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if not c.startswith("_") and c != "target"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", default="data/features_train.parquet")
    ap.add_argument("--oos", default="data/features_oos.parquet")
    args = ap.parse_args()

    train = pd.read_parquet(args.train)
    oos = pd.read_parquet(args.oos)
    feats = _feature_cols(train)

    # --- モデル(較正済み) ---
    model = CalibratedWinModel(method="isotonic").fit(train, feature_cols=feats)
    oos_model_p = model.predict_proba(oos, feature_cols=feats)

    # --- ベースライン ---
    baseline = PopularityBaseline().fit(train)
    oos_base_p = baseline.predict(oos)

    y = oos["target"].values
    m_metrics = compute_metrics(y, oos_model_p)
    b_metrics = compute_metrics(y, oos_base_p)

    oos_m = oos.copy(); oos_m["_pred"] = oos_model_p
    oos_b = oos.copy(); oos_b["_pred"] = oos_base_p
    m_race = compute_race_level_metrics(oos_m, pred_col="_pred")
    b_race = compute_race_level_metrics(oos_b, pred_col="_pred")

    print("=== OOS comparison (model vs popularity baseline) ===")
    print(f"Brier   model={m_metrics['brier']:.5f}  baseline={b_metrics['brier']:.5f}")
    print(f"LogLoss model={m_metrics['logloss']:.5f}  baseline={b_metrics['logloss']:.5f}")
    print(f"AUC     model={m_metrics['auc']:.4f}  baseline={b_metrics['auc']:.4f}")
    print(f"top1hit model={m_race['top1_hit_rate']:.4f}  baseline={b_race['top1_hit_rate']:.4f}")

    beats = (
        m_metrics["brier"] < b_metrics["brier"]
        and m_metrics["logloss"] < b_metrics["logloss"]
        and m_race["top1_hit_rate"] >= b_race["top1_hit_rate"]
    )
    if beats:
        print("RESULT: PASS — model beats popularity baseline on OOS. 採用候補。")
    else:
        print("RESULT: FAIL — model does NOT beat baseline. 正直な結論: ベースライン採用 or 撤退を検討。")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 学習・評価を実行**

Run:
```bash
PYTHONPATH=src python scripts/train_win_model.py --train data/features_train.parquet --oos data/features_oos.parquet
```
Expected: 4指標の比較表と `RESULT: PASS` または `RESULT: FAIL`。

- [ ] **Step 3: 結果の解釈（合格ゲート）**

- `PASS` の場合: モデルはOOSで人気を上回る。次工程（P3: WIN5買い目最適化＋バックテスト）へ進める。
- `FAIL` の場合: **これは失敗ではなく正直な発見**。spec §6 の通り「人気ベースライン採用」または「機械学習による妙味なし＝WIN5は実弾時期尚早」を結論として記録する。安易にOOS期間や指標を都合よく変えて`PASS`を捏造しないこと。

- [ ] **Step 4: 結果をレポートに記録**

`docs/superpowers/specs/` に `2026-06-06-P2-result.md` を作成し、4指標の実数値・PASS/FAIL・解釈・次アクションを記録。

- [ ] **Step 5: Commit**

```bash
git add scripts/train_win_model.py docs/superpowers/specs/2026-06-06-P2-result.md
git commit -m "feat(win5-model): OOS train/eval vs popularity baseline + result report"
```

---

## Task 6: 全テスト確認とREADME更新

**Files:**
- Modify: `README.md`

- [ ] **Step 1: モデル系テスト全実行**

Run: `python -m pytest tests/test_model/ -v`
Expected: 全PASS（oos_split 2 + popularity_baseline 2 + calibration 2）

- [ ] **Step 2: README にP2手順を追記**

`README.md` の「## データ基盤の構築（P0/P1）」の後に追記:
```markdown
## 勝率モデル（P2）

```bash
# 特徴量生成（train期間 / OOS期間）
PYTHONPATH=src python scripts/build_training_data.py --start 2021-01-01 --end 2024-12-31 --out data/features_train.parquet
PYTHONPATH=src python scripts/build_training_data.py --start 2025-01-01 --end 2025-12-31 --out data/features_oos.parquet
# 較正モデル学習＋OOSで人気ベースライン比較
PYTHONPATH=src python scripts/train_win_model.py
```

合格条件: OOSで Brier・LogLoss がベースライン未満かつ top1 的中率がベースライン以上。
満たさなければ「ベースライン採用 or 撤退」を正直な結論とする（spec §6）。
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs(win5): document P2 win-probability model workflow"
```

---

## 完了の定義（このプランのスコープ）

- [ ] `tests/test_model/` 全PASS（oos_split / popularity_baseline / calibration）
- [ ] `data/features_train.parquet` と `data/features_oos.parquet` を生成
- [ ] `train_win_model.py` がOOS比較を出力し、PASS/FAILを明示
- [ ] P2結果レポート（4指標の実数値・解釈・次アクション）を記録

PASS なら P3（WIN5買い目最適化＋バックテスト）プランを作成。FAIL なら結論（ベースライン採用/撤退）をユーザーへ提示して方針相談。

---

## Self-Review メモ（spec照合）

- spec §6 確率較正必須 → Task 3 CalibratedWinModel
- spec §6 ウォークフォワード/OOSのみで評価 → Task 1 time_split + Task 5 OOS評価
- spec §6 人気ベースライン超えを合格条件 → Task 2 + Task 5 比較ゲート
- spec §7 P2 合格基準（OOS Brier/LogLoss較正OK・人気超え）→ Task 5 Step 2/3
- spec §3 popularity の取込（P2前提）→ Task 0
- 性能リスク（特徴量生成）→ Task 4 スモーク優先＋ローカルDB回避策
- 過学習捏造防止 → Task 5 Step 3（指標/期間の都合変更禁止を明記）
