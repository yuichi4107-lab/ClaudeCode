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

---

## JRA 中央競馬予想システム (jra_predictor)

### Overview
JRA 中央競馬10場（札幌・函館・福島・新潟・東京・中山・中京・京都・阪神・小倉）を対象とした馬単予想システム。
nankan_predictor と同一アーキテクチャで、netkeiba.com からデータを収集し LightGBM で馬単を予測する。

### Usage
```bash
# 過去データ収集
python -m jra_predictor.cli.main scrape --from-date 2024-01-01 --to-date 2025-12-31

# 特定日付・会場
python -m jra_predictor.cli.main scrape --date 20260215 --venue tokyo

# モデル学習
python -m jra_predictor.cli.main train --from-date 2024-01-01 --to-date 2025-12-31

# 当日予想
python -m jra_predictor.cli.main predict --date 20260215 --venue tokyo --top-n 3

# バックテスト ROI 評価
python -m jra_predictor.cli.main evaluate --from-date 2026-01-01

# setup.py でインストール後はショートカットが使える
jra scrape --date 20260215
jra predict --date 20260215 --venue hanshin
```

### Architecture
```
jra_predictor/
├── config/settings.py      会場コード (01=札幌〜10=小倉)、URL、レート制限
├── scraper/
│   ├── base.py             レート制限 (3秒+ジッター)・HTMLキャッシュ付き HTTP セッション
│   ├── race_list.py        db.netkeiba.com からレースIDリスト取得
│   ├── race_result.py      確定レース結果スクレイプ (db.netkeiba.com/race/{race_id}/)
│   ├── race_entry.py       出馬表スクレイプ (race.netkeiba.com/race/shutuba.html)
│   └── horse_history.py    馬の過去成績スクレイプ (db.netkeiba.com/horse/result/{horse_id}/)
├── storage/
│   ├── database.py         SQLite スキーマ定義・接続管理 (WAL モード) - course_direction 列追加
│   └── repository.py       CRUD: upsert_race, upsert_entries, get_entries_in_range 等
├── features/builder.py     特徴量生成 (28特徴量)。芝/ダート適性・コース方向を追加
├── model/
│   ├── trainer.py          TimeSeriesSplit + LightGBM/HGBT + CalibratedClassifierCV
│   ├── predictor.py        2モデル(win/place)から馬単組み合わせ確率を計算
│   ├── evaluation.py       馬単ROI バックテスト
│   └── registry.py         joblib でモデル保存・読み込み (data/models/)
└── cli/main.py             argparse エントリーポイント (scrape/train/predict/evaluate)
```

### JRA固有の設計
- **会場**: 01=札幌, 02=函館, 03=福島, 04=新潟, 05=東京, 06=中山, 07=中京, 08=京都, 09=阪神, 10=小倉
- **コース種別**: 芝・ダート・障害の3種。nankan_predictor は基本ダートのみ
- **コース方向**: 右回り・左回り・直線の区別を特徴量に追加
- **出馬表URL**: race.netkeiba.com（JRA用）。nankan は nar.netkeiba.com
- **DB**: data/jra.db（nankan とは別ファイル）
- **特徴量**: horse_same_track_type_win_rate (芝/ダート適性), course_direction_enc を追加 (計28特徴量)
