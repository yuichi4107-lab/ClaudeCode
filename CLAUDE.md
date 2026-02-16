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
JRA 中央競馬10場（札幌・函館・福島・新潟・東京・中山・中京・京都・阪神・小倉）を対象とした馬連・三連複予想システム。
nankan_predictor と同一アーキテクチャで、netkeiba.com からデータを収集し LightGBM で馬連・三連複を予測する。

### Usage
```bash
# 過去データ収集
python -m jra_predictor.cli.main scrape --from-date 2024-01-01 --to-date 2025-12-31

# 特定日付・会場
python -m jra_predictor.cli.main scrape --date 20260215 --venue tokyo

# モデル学習
python -m jra_predictor.cli.main train --from-date 2024-01-01 --to-date 2025-12-31

# 当日予想（馬連）
python -m jra_predictor.cli.main predict --date 20260215 --venue tokyo --top-n 3 --bet-type quinella

# 当日予想（三連複）
python -m jra_predictor.cli.main predict --date 20260215 --venue tokyo --top-n 3 --bet-type trio

# 厳選予想: 1日最大5R、自信度上位のみ（推奨）
python -m jra_predictor.cli.main predict --date 20260215 --bet-type trio --max-races 5
python -m jra_predictor.cli.main predict --date 20260215 --bet-type quinella --max-races 4 --min-confidence 2.0

# 三連複ボックス買い: 4頭BOX(4点) or 5頭BOX(10点)
python -m jra_predictor.cli.main predict --date 20260215 --bet-type trio --box 4 --max-races 5
python -m jra_predictor.cli.main predict --date 20260215 --bet-type trio --box 5 --max-races 4

# バックテスト ROI 評価（全レース）
python -m jra_predictor.cli.main evaluate --from-date 2026-01-01 --bet-type quinella
python -m jra_predictor.cli.main evaluate --from-date 2026-01-01 --bet-type trio

# バックテスト ROI 評価（選択的: 1日最大6R、日別成績付き）
python -m jra_predictor.cli.main evaluate --from-date 2026-01-01 --bet-type trio --max-races 6
python -m jra_predictor.cli.main evaluate --from-date 2026-01-01 --bet-type quinella --max-races 4 --min-confidence 2.0

# バックテスト（三連複ボックス: 1日5R × 4頭BOX = 20点/日）
python -m jra_predictor.cli.main evaluate --from-date 2026-01-01 --bet-type trio --box 4 --max-races 5
python -m jra_predictor.cli.main evaluate --from-date 2026-01-01 --bet-type trio --box 5 --max-races 4

# setup.py でインストール後はショートカットが使える
jra scrape --date 20260215
jra predict --date 20260215 --venue hanshin --bet-type trio
jra predict --date 20260215 --bet-type trio --box 4 --max-races 5
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
├── features/builder.py     特徴量生成 (33特徴量)。上がり3F・馬齢・モメンタム等を追加
├── model/
│   ├── trainer.py          TimeSeriesSplit + LightGBM/HGBT + CalibratedClassifierCV
│   ├── predictor.py        3モデル(win/place/top3)から馬連・三連複確率を計算
│   ├── evaluation.py       馬連・三連複 ROI バックテスト（全レース・選択的）
│   ├── strategy.py         選択的ベッティング: 自信度スコア算出・レース選出
│   └── registry.py         joblib でモデル保存・読み込み (data/models/)
└── cli/main.py             argparse エントリーポイント (scrape/train/predict/evaluate --bet-type quinella/trio --max-races)
```

### JRA固有の設計
- **会場**: 01=札幌, 02=函館, 03=福島, 04=新潟, 05=東京, 06=中山, 07=中京, 08=京都, 09=阪神, 10=小倉
- **コース種別**: 芝・ダート・障害の3種。nankan_predictor は基本ダートのみ
- **コース方向**: 右回り・左回り・直線の区別を特徴量に追加
- **出馬表URL**: race.netkeiba.com（JRA用）。nankan は nar.netkeiba.com
- **DB**: data/jra.db（nankan とは別ファイル）
- **特徴量**: 33特徴量。上がり3F平均・前走人気・着順モメンタム・馬齢・性別・騎手3着以内率等を含む
- **馬券種**: 馬連 (quinella) と三連複 (trio) の2種対応。`--bet-type` オプションで切替
- **馬連確率**: `P(i,j) ≈ P_win(i)*P_place(j)/(1-P_win(i)) + P_win(j)*P_place(i)/(1-P_win(j))` で近似（順不同）
- **三連複確率**: `P(i,j,k) ≈ P_top3(i) * P_top3(j) * P_top3(k)` で近似（順不同）
- **モデル3本構成**: `{name}_win.joblib` + `{name}_place.joblib` + `{name}_top3.joblib`
- **選択的ベッティング**: `--max-races N` で1日あたりN件に絞り込み。自信度スコア = edge_ratio × (1 + separation/top1_prob) で算出
- **自信度スコア**: モデル予測確率 / ランダム確率（=優位率）× 確信度係数。高いほど買い
- **三連複ボックス**: `--box 4` (4頭=4点) / `--box 5` (5頭=10点)。P(top3)上位の馬を選出し全組み合わせ購入
- **推奨戦略**: ROI重視: `--bet-type trio --box 4 --max-races 5` (ROI+159%)、安定重視: `--bet-type trio --box 5 --max-races 5` (ROI+142%, 的中率4.6%)
- **データ移行**: 馬単(exacta)から馬連(quinella)への変更に伴い、払戻データの再スクレイプが必要（`bet_type='quinella'` で保存）
