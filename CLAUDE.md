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

## 成果物の保存ルール（必須）

このリポジトリで制作した**成果物はすべて** Google ドライブの `YNFactory-cc` フォルダに保存すること。
（ユーザーの PC では `G:\マイドライブ\YNFactory-cc` として同期される）

- **保存先フォルダ ID**: `1pTrN2vTBHiHLeYGt31zWSIofwgFjqF9M`
  （https://drive.google.com/drive/folders/1pTrN2vTBHiHLeYGt31zWSIofwgFjqF9M）
- **アップロード方法**: Google Drive MCP の `create_file` ツールを使用し、`parentId` に上記フォルダ ID を指定する
  - テキスト系（.md / .csv / .txt / .html 等）→ `textContent` に内容を渡す
  - バイナリ系（.xlsx / .pdf / .png / .joblib 等）→ `base64Content` に base64 エンコードして渡す
  - `contentMimeType` を必ず内容に合わせて指定する
  - `disableConversionToGoogleType: true` を指定し、Google ドキュメント形式への変換を防いで元のファイル形式のまま保存する（G ドライブ上でそのまま開けるようにするため）
- **ファイル名**: Drive は同名ファイルを重複作成するため、`YYYYMMDD_ファイル名.拡張子` のように日付プレフィックスを付ける

### 対象（成果物のみ）
- ユーザーに納品する最終ファイル: レポート、予想結果、分析結果、CSV/Excel、画像、ドキュメント等
- 明示的に依頼された生成物すべて

### 対象外
- ソースコード（git で管理するためアップロード不要）
- 中間ファイル・一時ファイル・スクラッチパッドの作業ファイル
- `data/cache/` の HTML キャッシュ、ログ、SQLite DB

成果物を作成したら、その同一ターン内でアップロードまで完了させ、Drive 上のファイル URL をユーザーに報告すること。

## Key Design Decisions
- **馬単確率の計算**: `P(i→j) ≈ P_win(i) * P_place(j) / (1 - P_win(i))` で近似。1着モデルと2着モデルを分けて学習する
- **モデルファイル命名**: `{model_name}_win.joblib` と `{model_name}_place.joblib` の2本構成
- **未来リーク防止**: FeatureBuilder は `before_date` パラメータで対象レース日付より前のデータのみ使用
- **レースID形式**: `YYYY` + `VV`(会場2桁) + `MMDD` + `RR`(レース番号)
- **モデル**: LightGBM 優先。未インストールなら sklearn の HistGradientBoostingClassifier にフォールバック
- **払戻金**: `race_payouts` テーブルに馬単払戻金を保存。ROIバックテストに使用
- **キャッシュ**: `data/cache/` に HTML をキャッシュ（MD5 ハッシュ名）。再スクレイプを避ける
