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

## FX自動売買システム (fx_trader)

### Overview
FX（外国為替）の自動売買システム。OANDA API でデータ取得・注文執行し、
テクニカル指標を特徴量として LightGBM で価格方向を予測するハイブリッド戦略。

### Setup
```bash
# 環境変数設定 (OANDA デモ口座)
export OANDA_API_KEY="your-api-key"
export OANDA_ACCOUNT_ID="your-account-id"
export OANDA_ENVIRONMENT="practice"

# インストール
pip install -e . -f setup_fx.py
# or
pip install -r fx_trader/requirements.txt
```

### Usage
```bash
# 過去データ取得
python -m fx_trader.cli.main fetch --from-date 2024-01-01 --to-date 2025-12-31
python -m fx_trader.cli.main fetch --instruments USD_JPY,EUR_USD --granularity H1

# モデル学習
python -m fx_trader.cli.main train --from-date 2024-01-01 --to-date 2025-12-31

# 売買シグナル生成
python -m fx_trader.cli.main predict --instruments USD_JPY --threshold 0.55

# バックテスト
python -m fx_trader.cli.main backtest --from-date 2025-01-01 --to-date 2025-12-31

# 自動売買 (DRY RUN)
python -m fx_trader.cli.main trade --dry-run

# 自動売買 (LIVE - 実際に発注)
python -m fx_trader.cli.main trade --live

# 保存済みモデル一覧
python -m fx_trader.cli.main models

# setup_fx.py でインストール後はショートカットが使える
fxtrade fetch --from-date 2024-01-01
fxtrade predict --instruments USD_JPY
```

### Architecture
```
fx_trader/
├── config/settings.py          通貨ペア、OANDA API設定、リスク管理パラメータ
├── data_fetcher/
│   ├── oanda_client.py         OANDA REST API v20 クライアント (認証・レート制限・リトライ)
│   └── fetcher.py              データ取得→DB保存の統合レイヤー
├── storage/
│   ├── database.py             SQLite スキーマ (candles, trades, signals, account_snapshots)
│   └── repository.py           CRUD: upsert_candles, get_candles, insert_trade 等
├── features/builder.py         テクニカル指標 (SMA/EMA/RSI/MACD/BB/ATR) → ML特徴量
├── model/
│   ├── trainer.py              TimeSeriesSplit + LightGBM + CalibratedClassifierCV
│   ├── predictor.py            学習済みモデルで売買シグナル (buy/sell/hold) を生成
│   ├── evaluation.py           バックテスト (Sharpe, ROI, MaxDD, ProfitFactor)
│   └── registry.py             joblib でモデル保存・読み込み (data/fx/models/)
├── trading/
│   ├── executor.py             シグナル→OANDA発注の自動執行 (dry_run対応)
│   └── risk_manager.py         ポジションサイズ計算、日次損失制限、SL/TP計算
└── cli/main.py                 argparse エントリーポイント (fetch/train/predict/backtest/trade/models)
```

### Data Flow
1. `fetch` → OANDA API から OHLCV ローソク足を取得 → SQLite (candles テーブル) に保存
2. `train` → FeatureBuilder でテクニカル指標特徴量生成 → ModelTrainer で学習 → data/fx/models/ に保存
3. `predict` → 最新データから特徴量生成 → モデル推論 → buy/sell/hold シグナル出力
4. `backtest` → 過去データで擬似売買 → ROI・Sharpe・MaxDrawdown 等を評価
5. `trade` → predict + 発注実行 (dry_run / live)

### Key Design Decisions
- **ハイブリッド戦略**: テクニカル指標 (SMA, RSI, MACD, BB, ATR) を特徴量として LightGBM に入力
- **方向予測**: forward_periods 先の終値 vs 現在終値で up/down を二値分類
- **リスク管理**: 1トレードあたり口座残高の2%リスク、日次5%損失上限、最大3ポジション
- **SL/TP計算**: ATR ベースの動的計算 (SL=1.5ATR, TP=3ATR) またはデフォルト固定値
- **DRY RUN**: デフォルトは注文を出さない安全モード。--live で実注文
- **モデル**: LightGBM 優先、sklearn HistGradientBoostingClassifier フォールバック
- **データ保存**: data/fx/ 以下に SQLite (fx_trader.db) とモデルファイルを格納
