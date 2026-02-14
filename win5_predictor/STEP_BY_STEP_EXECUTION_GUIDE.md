# 実行ステップバイステップガイド

目標：JRA Win5 予想システムを段階的に実行し、本番運用準備を進める

---

## 🎯 段階別実行計画

各段階の推定時間、必要な手順、確認方法をリスト化します。

### 段階1: セットアップ準備 ⏱️ 30分

**目標**: 開発環境の準備完了

**チェックリスト**:
```
□ ステップ1-1: リポジトリをクローン
□ ステップ1-2: 仮想環境を作成
□ ステップ1-3: 依存パッケージをインストール
□ ステップ1-4: インストール確認
```

**実行コマンド**:
```bash
# ステップ1-1: リポジトリをクローン
git clone https://github.com/yuichi4107-lab/ClaudeCode.git
cd ClaudeCode/win5_predictor

# ステップ1-2: 仮想環境を作成
python -m venv venv

# ステップ1-3: 仮想環境を有効化
# Windows
venv\Scripts\activate
# macOS/Linux
source venv/bin/activate

# ステップ1-4: パッケージをインストール
pip install --upgrade pip
pip install -r requirements.txt

# ステップ1-5: インストール確認
pip list | grep -E "lightgbm|scikit|pandas|optuna|streamlit"
```

**期待される出力**:
```
lightgbm          4.x.x
scikit-learn      1.3.x
pandas            2.0.x
optuna            3.0.x
streamlit         1.28.x
... (その他)
```

**進捗**: ✅ セットアップ準備完了

---

### 段階2: システム確認 ⏱️ 5分

**目標**: システムが正常に動作することを確認

**実行コマンド**:
```bash
# システムステータス確認
python -m app.cli status
```

**期待される出力**:
```
Win5 Predictor Status
┌──────────────────┬──────────────────────────┐
│ Item             │ Value                    │
├──────────────────┼──────────────────────────┤
│ DB Path          │ /path/to/data/win5.db    │
│ DB Exists        │ True                     │
│ Races            │ 0 (初回は0)               │
│ Results          │ 0 (初回は0)               │
│ Date Range       │ N/A                      │
│ Active Model     │ None (初回はNone)        │
│ Models Dir       │ /path/to/models          │
└──────────────────┴──────────────────────────┘
```

**確認項目**:
- ✅ DB Path が表示されている
- ✅ DB Exists が True
- ✅ エラーが出ていない

**トラブル時の対応**:
```bash
# Python パスを確認
which python  # macOS/Linux
where python  # Windows

# モジュールが見つからない場合
pip install lightgbm scikit-learn pandas numpy optuna shap click streamlit --force-reinstall
```

**進捗**: ✅ システム確認完了

---

### 段階3: テスト実行 ⏱️ 5-10分

**目標**: テストスイート（73テスト）が全てPASSすることを確認

**実行コマンド**:
```bash
# 全テスト実行
pytest tests/ -v

# または特定フェーズのみ
pytest tests/test_phase1_foundation.py -v
pytest tests/test_phase2_integration.py -v
# ... etc
```

**期待される出力**:
```
tests/test_phase1_foundation.py::test_database_initialization PASSED
tests/test_phase1_foundation.py::test_repository_crud PASSED
...
tests/test_phase7_app.py::test_cli_version PASSED
tests/test_phase7_app.py::test_cli_help PASSED

======================== 73 passed in 15.23s ========================
```

**確認項目**:
- ✅ Total: 73 passed
- ✅ Failed: 0
- ✅ 実行時間: 10-20秒

**トラブル時の対応**:
```bash
# pytest がない場合
pip install pytest pytest-cov

# 特定テストのみ実行して原因を特定
pytest tests/test_phase1_foundation.py::test_database_initialization -v
```

**進捗**: ✅ テスト実行完了

---

### 段階4: ダッシュボード起動 ⏱️ 5分

**目標**: Streamlit ダッシュボードが正常に起動

**実行コマンド**:
```bash
# ダッシュボード起動
python -m app.cli dashboard

# または ポート変更
python -m app.cli dashboard --port 8502
```

**期待される出力**:
```
  You can now view your Streamlit app in your browser.

  Local URL: http://localhost:8501
  Network URL: http://192.168.1.x:8501
```

**ブラウザアクセス**:
1. ブラウザを開く
2. http://localhost:8501 にアクセス
3. ページが読み込まれることを確認

**ダッシュボード確認**:
```
✅ 画面が表示される
✅ メニューが表示される
✅ サイドバーから「システム状態」を選択できる
✅ DB統計が表示される（Races: 0, Results: 0）
```

**進捗**: ✅ ダッシュボード起動確認

---

### 段階5: テストデータ収集 ⏱️ 30-60分

**目標**: 直近3ヶ月のデータを収集

**実行コマンド**:
```bash
# 2024年のテストデータを収集
python -m app.cli collect --start 2024-01-01 --end 2024-03-31

# または進捗をリアルタイムで確認しながら実行
python -m app.cli collect --start 2024-01-01 --end 2024-03-31 2>&1 | tee collect_test.log
```

**期待される出力**:
```
[2026-02-14 12:00:00] Collecting races from 2024-01-01 to 2024-03-31...
[2026-02-14 12:00:05] Downloaded: 2024-01-07 (races: 4)
[2026-02-14 12:00:15] Downloaded: 2024-01-14 (races: 5)
[2026-02-14 12:00:25] Downloaded: 2024-01-21 (races: 4)
...
[2026-02-14 12:15:00] Total: 52 races, 728 results downloaded
```

**確認項目**:
```bash
# データベースを確認
python -m app.cli status

期待される出力:
□ Races: 50+ (テストデータ)
□ Results: 500+ (テストレコード)
□ Date Range: 2024-01-07 ~ 2024-03-31
```

**進捗**: ✅ テストデータ収集完了

---

### 段階6: モデル学習（テスト） ⏱️ 10-20分

**目標**: テストデータでモデルを学習

**実行コマンド**:
```bash
# 基本的な学習（高速）
python -m app.cli train --start 2024-01-01 --end 2024-02-29

# または Optuna で最適化（遅い）
python -m app.cli train --start 2024-01-01 --end 2024-02-29 --optimize --n-trials 20
```

**期待される出力**:
```
[2026-02-14 12:30:00] Building training data: 2024-01-01 to 2024-02-29
[2026-02-14 12:35:00] Training with 400 samples, 87 features
[2026-02-14 12:40:00] Time-series CV started (5 folds)
[2026-02-14 12:41:00] Fold 1: AUC=0.6245, LogLoss=0.3950
[2026-02-14 12:42:00] Fold 2: AUC=0.6512, LogLoss=0.3820
[2026-02-14 12:43:00] Fold 3: AUC=0.6398, LogLoss=0.3890
[2026-02-14 12:44:00] Fold 4: AUC=0.6410, LogLoss=0.3880
[2026-02-14 12:45:00] Fold 5: AUC=0.6284, LogLoss=0.3920
[2026-02-14 12:46:00] Training final model...
[2026-02-14 12:50:00] Model saved: model_id=2024-02-14-v1
[2026-02-14 12:50:00] Top 20 features:
  1. feature_horse_win_rate_5: 0.245
  2. feature_jockey_combo_wins: 0.198
  ...
```

**確認項目**:
```
✅ AUC が 0.60+ である
✅ LogLoss が 0.40 以下である
✅ model_id が表示される
✅ Top 20 features が表示される
```

**確認コマンド**:
```bash
python -m app.cli status

期待される出力:
□ Active Model: 2024-02-14-v1
□ Model AUC: 0.6354 (5-Fold 平均)
□ Features: 87
```

**進捗**: ✅ モデル学習完了

---

### 段階7: バックテスト実行 ⏱️ 5-10分

**目標**: 過去データでシミュレーション実行

**実行コマンド**:
```bash
# テストデータ（2024年）でバックテスト
python -m app.cli backtest --start 2024-01-01 --end 2024-03-31

# または異なる予算でテスト
python -m app.cli backtest --start 2024-01-01 --end 2024-03-31 --budget 5000
```

**期待される出力**:
```
==================================================
Backtest Results:
  Events: 13 (3ヶ月分の Win5 イベント)
  Hits: 0-1 (的中率 0-8%)
  Total Cost: ¥130,000
  Total Payout: ¥0-800,000
  Profit: -¥130,000 ～ +¥670,000
  ROI: -100% ～ +515%
==================================================

Monthly Summary:
  2024-01: 4 events, 0 hits, ROI: -100%
  2024-02: 5 events, 1 hit, ROI: +515%
  2024-03: 4 events, 0 hits, ROI: -100%

Max Drawdown: -¥130,000 (-100%)
```

**確認項目**:
```
✅ イベント数が表示される
✅ ROI が計算されている
✅ 月別成績が表示される
✅ エラーが出ていない
```

**進捗**: ✅ バックテスト実行完了

---

### 段階8: 予想実行（テスト） ⏱️ 2分

**目標**: Win5 予想を実行

**実行コマンド**:
```bash
# 指定日の予想を実行
python -m app.cli predict --date 2026-02-15 --budget 10000

# または小額でテスト
python -m app.cli predict --date 2026-02-15 --budget 3000
```

**期待される出力**:
```
[2026-02-14 13:00:00] Win5 Prediction for 2026-02-15 (Budget: ¥10,000)
[2026-02-14 13:00:05] Found 5 Win5 races
[2026-02-14 13:00:10] Predicting: Race 1 (5 horses)
[2026-02-14 13:00:11] Predicting: Race 2 (5 horses)
[2026-02-14 13:00:12] Predicting: Race 3 (4 horses)
[2026-02-14 13:00:13] Predicting: Race 4 (6 horses)
[2026-02-14 13:00:14] Predicting: Race 5 (5 horses)
[2026-02-14 13:00:15] Optimizing purchase combination...

Win5 推奨買い目
┌───────┬────┬───────────┬──────────────┐
│ Race  │ 馬 │ 馬名      │ 予測勝率     │
├───────┼────┼───────────┼──────────────┤
│ R1    │ 2  │ 馬A       │ 28.5%        │
│       │ 4  │ 馬B       │ 22.3%        │
│       │ 6  │ 馬C       │ 18.9%        │
│ R2    │ 1  │ 馬D       │ 31.2%        │
│       │ 3  │ 馬E       │ 19.5%        │
...

  組合せ数: 72 | 購入金額: ¥7,200 | 的中確率: 0.145% | 期待値: -¥2,686
```

**確認項目**:
```
✅ 5レースのレースIDが表示される
✅ 各レースの馬番・馬名・勝率が表示される
✅ 買い目組み合わせ数が表示される
✅ 購入金額が予算以下である
✅ 期待値が計算されている
```

**進捗**: ✅ 予想実行完了

---

### 段階9: 本番データ準備 ⏱️ 50-100時間（バックグラウンド実行）

**目標**: 2015-2026年の完全なデータセットを構築

**実行コマンド**:
```bash
# バックグラウンドで実行開始
nohup python -m app.cli collect --start 2015-01-01 --end 2025-12-31 > collect_full.log 2>&1 &

# または screen/tmux で実行
screen -S win5_collect
python -m app.cli collect --start 2015-01-01 --end 2025-12-31
# Ctrl+A, D で離脱
```

**進捗確認**:
```bash
# リアルタイムログ確認
tail -f collect_full.log

# または定期的に確認
watch -n 10 "tail -10 collect_full.log"
```

**期待される完成時間**:
```
- 高速ネットワーク（1Gbps）: 50-60時間
- 標準ネットワーク（100Mbps）: 80-100時間
- 推奨実行時間: 金曜 PM 2:00 開始 → 翌週月曜 PM 6:00 完了
```

**進捗**: ✅ 本番データ収集開始

---

### 段階10: 本番モデル学習 ⏱️ 2-4時間

**（段階9の完了後に実行）**

**目標**: 完全なデータセットでモデルを学習

**実行コマンド**:
```bash
# データ収集完了を確認してから実行
python -m app.cli status  # Races: 45,000+ を確認

# 本番モデル学習（高速）
python -m app.cli train --start 2020-01-01 --end 2024-12-31

# または最適化付き（推奨）
python -m app.cli train --start 2020-01-01 --end 2024-12-31 --optimize --n-trials 100
```

**期待される出力**:
```
[日時] Building training data: 2020-01-01 to 2024-12-31
[日時] Training with 3500+ samples, 87 features
[日時] Time-series CV started (5 folds)
[日時] Fold 1: AUC=0.6750, LogLoss=0.3800
[日時] Fold 2: AUC=0.6680, LogLoss=0.3820
[日時] Fold 3: AUC=0.6820, LogLoss=0.3750
[日時] Fold 4: AUC=0.6710, LogLoss=0.3810
[日時] Fold 5: AUC=0.6680, LogLoss=0.3830
[日時] Average AUC: 0.6728 ✅ (目標達成)
...
[日時] Model saved: model_id=2026-02-14-prod-v1
```

**確認項目**:
```
✅ 平均 AUC が 0.65+ である
✅ model_id が表示される
✅ Top 20 features が表示される
```

**進捗**: ✅ 本番モデル学習完了

---

### 段階11: 本番バックテスト ⏱️ 5-15分

**（段階10の完了後に実行）**

**目標**: 2年以上の過去データで本番検証

**実行コマンド**:
```bash
# 本番バックテスト実行
python -m app.cli backtest --start 2023-01-01 --end 2025-12-31

# または CSV に出力
python -m app.cli backtest --start 2023-01-01 --end 2025-12-31 > backtest_results.csv
```

**期待される出力**:
```
==================================================
Backtest Results:
  Events: 156 (3年分の Win5 イベント)
  Hits: 2-5 (的中率 1-3%)
  Total Cost: ¥1,560,000
  Total Payout: ¥1,200,000 ～ ¥2,500,000
  Profit: -¥360,000 ～ +¥940,000
  ROI: -23% ～ +60%
==================================================

Monthly Summary:
  2023-01: 4 events, 0 hits, ROI: -100%
  ...
  2025-11: 4 events, 1 hit, ROI: +580%

Max Drawdown: -¥480,000 (-31%)
Max Consecutive Losses: 12週
```

**確認項目**:
```
✅ イベント数が 100+ である
✅ ROI が計算されている
✅ ドローダウン情報が表示されている
✅ 月別成績が表示されている
```

**本番運用の判断基準**:
```
ROI > 0%          → ✅ ベット対象（期待値プラス）
ROI < 0%          → ⚠️ 再検討（期待値マイナス）
Max DD > ¥500,000 → ⚠️ リスク大（資金計画見直し）
```

**進捗**: ✅ 本番バックテスト完了

---

### 段階12: 本番運用開始 ⏱️ 継続運用

**目標**: 毎週日曜の Win5 予想を自動実行

**自動化設定（cron）**:

```bash
# crontab を編集
crontab -e

# 以下の行を追加（毎週日曜 AM 8:00 実行）
0 8 * * 0 cd /path/to/win5_predictor && python -m app.cli predict --date $(date +\%Y-\%m-\%d) --budget 10000 >> /var/log/win5/prediction.log 2>&1

# データ更新（毎週金曜 PM 2:00）
0 14 * * 5 cd /path/to/win5_predictor && python -m app.cli collect --start $(date -d "yesterday" +\%Y-\%m-\%d) --end $(date +\%Y-\%m-\%d) >> /var/log/win5/collect.log 2>&1

# モデル再学習（毎月初 AM 0:00）
0 0 1 * * cd /path/to/win5_predictor && python -m app.cli train --start $(date -d "3 months ago" +\%Y-\%m-\%d) --end $(date +\%Y-\%m-\%d) >> /var/log/win5/train.log 2>&1
```

**進捗**: ✅ 本番運用開始完了

---

## 📊 進捗チェックリスト全体

```
□ 段階1: セットアップ準備             (推定 30分)
□ 段階2: システム確認                 (推定 5分)
□ 段階3: テスト実行                   (推定 10分)
□ 段階4: ダッシュボード起動           (推定 5分)
□ 段階5: テストデータ収集             (推定 30分)
□ 段階6: モデル学習（テスト）         (推定 20分)
□ 段階7: バックテスト実行             (推定 10分)
□ 段階8: 予想実行（テスト）           (推定 2分)
──────────────────────────────────────────────────
θ 小計: 段階1-8                       (推定 1時間 52分)

□ 段階9: 本番データ準備               (推定 50-100時間)
□ 段階10: 本番モデル学習              (推定 2-4時間)
□ 段階11: 本番バックテスト            (推定 10分)
□ 段階12: 本番運用開始                (継続運用)
──────────────────────────────────────────────────
合計: 約 55-110 時間（データ収集含む）
```

---

## 🚀 どこから始めますか？

**推奨**: 段階1からスタートしてください！

次のステップは、以下のコマンドを実行してください：

```bash
# ステップ1-1: リポジトリをクローン
git clone https://github.com/yuichi4107-lab/ClaudeCode.git
cd ClaudeCode/win5_predictor

# ステップ1-2: 仮想環境を作成
python -m venv venv

# ステップ1-3: 有効化（以下の適切なコマンドを選択）
# Windows
venv\Scripts\activate
# macOS/Linux
source venv/bin/activate

# ステップ1-4: パッケージをインストール
pip install --upgrade pip
pip install -r requirements.txt

# ステップ1-5: インストール確認
pip list | grep -E "lightgbm|scikit|pandas"
```

完了したら、次のコマンドを実行してください：

```bash
python -m app.cli status
```

**今すぐ段階1を開始しますか？** 🚀

