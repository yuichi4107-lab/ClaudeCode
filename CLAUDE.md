# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview
南関東4場（大井・船橋・川崎・浦和）を対象とした地方競馬馬単予想システム。
netkeiba.com からスクレイピングしたデータを SQLite に蓄積し、機械学習（LightGBM / sklearn）で馬単（1着→2着の組み合わせ）を予測する。

## Commands

### Setup
```bash
pip install -e .
# or
pip install -r requirements.txt
```

### Usage
```bash
# 過去データ収集（月単位でループ）
python -m nankan_predictor.cli.main scrape --from-date 2024-01-01 --to-date 2025-12-31

# 特定日付のみ
python -m nankan_predictor.cli.main scrape --date 20260212

# モデル学習
python -m nankan_predictor.cli.main train --from-date 2024-01-01 --to-date 2025-12-31

# 当日予想
python -m nankan_predictor.cli.main predict --date 20260212 --venue oi --top-n 3

# バックテスト ROI 評価
python -m nankan_predictor.cli.main evaluate --from-date 2026-01-01

# setup.py でインストール後はショートカットが使える
nankan scrape --date 20260212
nankan predict --date 20260212
```

## Architecture

```
nankan_predictor/
├── config/settings.py      会場コード (44=浦和,45=船橋,46=大井,47=川崎)、URL、レート制限
├── scraper/
│   ├── base.py             レート制限 (3秒+ジッター)・HTMLキャッシュ付き HTTP セッション
│   ├── race_list.py        db.netkeiba.com からレースIDリスト取得
│   ├── race_result.py      確定レース結果スクレイプ (db.netkeiba.com/race/{race_id}/)
│   ├── race_entry.py       出馬表スクレイプ (nar.netkeiba.com/race/shutuba.html)
│   └── horse_history.py    馬の過去成績スクレイプ (db.netkeiba.com/horse/result/{horse_id}/)
├── storage/
│   ├── database.py         SQLite スキーマ定義・接続管理 (WAL モード)
│   └── repository.py       CRUD: upsert_race, upsert_entries, get_entries_in_range 等
├── features/builder.py     特徴量生成。必ず before_date でフィルタして未来リークを防ぐ
├── model/
│   ├── trainer.py          TimeSeriesSplit + LightGBM/HGBT + CalibratedClassifierCV
│   ├── predictor.py        2モデル(win/place)から馬単組み合わせ確率を計算
│   ├── evaluation.py       馬単ROI バックテスト
│   └── registry.py         joblib でモデル保存・読み込み (data/models/)
└── cli/main.py             argparse エントリーポイント (scrape/train/predict/evaluate)
```

## Data Flow
1. `scrape` → races / race_entries / horse_history_cache を SQLite に保存
2. `train` → FeatureBuilder で特徴量生成 → ModelTrainer で学習 → data/models/ に保存
3. `predict` → 出馬表を取得 → 特徴量生成 → モデル推論 → ランキング出力

## Key Design Decisions
- **馬単確率の計算**: `P(i→j) ≈ P_win(i) * P_place(j) / (1 - P_win(i))` で近似。1着モデルと2着モデルを分けて学習する
- **モデルファイル命名**: `{model_name}_win.joblib` と `{model_name}_place.joblib` の2本構成
- **未来リーク防止**: FeatureBuilder は `before_date` パラメータで対象レース日付より前のデータのみ使用
- **レースID形式**: `YYYY` + `VV`(会場2桁) + `MMDD` + `RR`(レース番号)
- **モデル**: LightGBM 優先。未インストールなら sklearn の HistGradientBoostingClassifier にフォールバック
- **払戻金**: `race_payouts` テーブルに馬単払戻金を保存。ROIバックテストに使用
- **キャッシュ**: `data/cache/` に HTML をキャッシュ（MD5 ハッシュ名）。再スクレイプを避ける

## autorace_evaluator（オートレース選手能力評価）

autorace.jp を対象としたオートレース選手の能力評価システム。`nankan_predictor` とは独立したパッケージ。
詳細は `autorace_evaluator/README.md` を参照。

```bash
# データ収集（probe方式: 期間×5場×R1-12 を直接叩き、404は scrape_log で再訪防止）
python -m autorace_evaluator.cli.main scrape --from-date 2025-07-01 --to-date 2026-07-01

# 選手能力評価（整備力・スタート力・突っ込み度 + 総合ランキング、CSV出力）
python -m autorace_evaluator.cli.main evaluate --from-date 2025-07-01 --to-date 2026-07-01

# 保存済みHTMLの単体パース（パーサ修正サイクルのデバッグ手段）
python -m autorace_evaluator.cli.main parse-html FILE --json [--save]
```

### 3指標
- **整備力**: 同一節・前日当日とも良走路のときの試走タイム差(前日−当日)。改善率・平均差・スコア
- **スタート力**: ST統計 + ダッシュ力(競走T−上がりT の序盤ロスをレース内センタリング+Ridgeで説明した残差)
- **突っ込み度**: 混戦時の期待着順残差(STは説明変数に入れない) + 重ハン時追い抜き量 `passed = 前にいた車数 − 先着された車数`

### 設計上の注意
- **実HTML未検証**: 開発環境から autorace.jp に接続できないため、パーサは想定DOMベース。
  実HTMLとの差異は `autorace_evaluator/parsers/selectors.py` の定数修正のみで吸収する設計
- **TIME_FORMAT**: 競走タイム・上がりタイムの掲載単位が総時間だった場合は
  `config/settings.py` の `TIME_FORMAT` を `"total"` に変更(metrics は to_per100m() 経由で追随)
- **縮約**: 少数出走選手は経験ベイズ縮約 n/(n+k) (k=10) で0(またはST全体平均)に寄せる。
  min_races=10 / min_pairs=5 未満はスコアNaN(参考行)
- DB は `data/autorace.db`、キャッシュは `data/autorace_cache/`(nankan と分離)
