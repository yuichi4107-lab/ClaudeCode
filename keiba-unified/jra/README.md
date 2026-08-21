# JRA中央競馬予想モジュール

## 統合内容
- **2026keiba**: 特徴量エンジニアリング(63列)、LightGBMモデル、Optuna最適化、Walk-Forward検証
- **keiba-predictor**: ライブモード(発走5分前予測)、Telegram配信、結果チェック、収支管理

## データ
- `data/keiba.db` — 2026keiba由来 (17,162R, 2021-2025, 全10場)
- `data/keiba_live.db` — keiba-predictor由来 (17,349R, ~2026-03-15, ライブ運用DB)
- `data/models/` — 学習済みモデル
- `data/features_all.pkl` — 特徴量キャッシュ(236,197行x63列)

## スクリプト（ライブ運用系）
- `scripts/run_live.py` — 発走5分前にオッズ取得→予測→Telegram通知
- `scripts/run_today.py` — 当日全レース予測レポート
- `scripts/check_results.py` — 結果照合→収支記録→Telegram通知

## スクリプト（分析系）
- `scripts/01_scrape_races.py` — データ収集
- `scripts/03_train_model.py` — モデル学習
- `scripts/04_run_backtest.py` — バックテスト
- `scripts/optimize_umaren_top2.py` — Optuna最適化

## src/ (2026keiba由来のモジュール群)
- `src/scraper/` — netkeiba.comスクレイパー
- `src/features/` — 特徴量エンジニアリング(63列)
- `src/models/` — LightGBMモデル
- `src/strategies/` — 馬連/三連複/穴馬戦略
- `src/backtest/` — Walk-Forwardバックテストエンジン
