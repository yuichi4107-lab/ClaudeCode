# セットアップガイド

JRA Win5 予想システムを環境構築し、実運用するためのステップバイステップガイドです。

## 目次

1. [システム要件](#システム要件)
2. [Windows での セットアップ](#windows-でのセットアップ)
3. [macOS/Linux での セットアップ](#macosvlinux-でのセットアップ)
4. [初期実行](#初期実行)
5. [トラブルシューティング](#トラブルシューティング)

---

## システム要件

### 最小要件
```
OS: Windows 10+, macOS 10.15+, Linux (Ubuntu 20.04+)
Python: 3.10 以上
メモリ: 4GB 以上（8GB 推奨）
ディスク: 10GB 以上（データ収集時は 20GB+）
ネットワーク: インターネット接続（スクレイピング用）
```

### 推奨環境
```
OS: Windows 11, macOS 12+, or Ubuntu 22.04+
Python: 3.11 or 3.12
メモリ: 8GB 以上
ディスク: 50GB（完全データセット用）
```

---

## Windows でのセットアップ

### ステップ 1: Python インストール

1. [python.org](https://www.python.org/downloads/) から Python 3.11+ をダウンロード
2. インストーラを実行
   - **重要**: 「Add Python to PATH」にチェックを入れる
   - 完全なコースをお勧め（pip が自動インストールされます）

3. インストール確認
   ```bash
   python --version
   pip --version
   ```

### ステップ 2: リポジトリのクローン

```bash
# Git がない場合はインストール: https://git-scm.com/

git clone https://github.com/yuichi4107-lab/ClaudeCode.git
cd ClaudeCode/win5_predictor
```

### ステップ 3: 仮想環境の作成（推奨）

```bash
# 仮想環境を作成
python -m venv venv

# 仮想環境を有効化
venv\Scripts\activate

# 有効化の確認
(venv) C:\path\to\win5_predictor>
```

### ステップ 4: 依存パッケージのインストール

```bash
# 仮想環境が有効な状態で実行
pip install -r requirements.txt

# インストール進行状況を確認
pip list
```

**インストール時間**: 5-10分（インターネット速度に依存）

### ステップ 5: システム確認

```bash
# DB初期化とシステムステータス確認
python -m app.cli status
```

**期待される出力**:
```
Win5 Predictor Status
┌──────────────────┬─────────────────────┐
│ Item             │ Value               │
├──────────────────┼─────────────────────┤
│ DB Path          │ C:\path\to\win5.db  │
│ DB Exists        │ True                │
│ Races            │ 0                   │
│ Results          │ 0                   │
...
```

✅ 表示されたら Windows セットアップ完了！

---

## macOS/Linux でのセットアップ

### ステップ 1: Python インストール

#### macOS
```bash
# Homebrew でインストール（Homebrew が必要）
brew install python@3.11

# または
# MacPorts: sudo port install python311
```

#### Ubuntu/Debian
```bash
sudo apt update
sudo apt install python3.11 python3.11-venv python3-pip
```

### ステップ 2: リポジトリのクローン

```bash
git clone https://github.com/yuichi4107-lab/ClaudeCode.git
cd ClaudeCode/win5_predictor
```

### ステップ 3: 仮想環境の作成

```bash
# 仮想環境を作成
python3.11 -m venv venv

# 有効化
source venv/bin/activate

# 確認
(venv) $
```

### ステップ 4: 依存パッケージのインストール

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### ステップ 5: システム確認

```bash
python -m app.cli status
```

✅ セットアップ完了！

---

## 初期実行

### 1. データ収集（推定 50-100 時間）

```bash
# バックグラウンドで実行（推奨）
nohup python -m app.cli collect --start 2015-01-01 --end 2025-12-31 > collect.log 2>&1 &

# または前景で実行（テスト用）
python -m app.cli collect --start 2023-01-01 --end 2024-12-31

# 進捗確認（別ターミナル）
tail -f collect.log
```

**期待される出力**:
```
[2026-02-14 12:00:00] Collecting races from 2023-01-01 to 2024-12-31...
[2026-02-14 12:00:05] Downloaded: 2023-01-08 (4 races)
[2026-02-14 12:00:15] Downloaded: 2023-01-15 (5 races)
...
```

### 2. モデル学習

```bash
# 基本的な学習（高速）
python -m app.cli train --start 2020-01-01 --end 2024-12-31

# または Optuna で自動最適化（遅い、推定 1-2 時間）
python -m app.cli train --start 2020-01-01 --end 2024-12-31 --optimize --n-trials 100

# 進捗表示
# [2026-02-14 14:30:00] Building training data...
# [2026-02-14 14:35:00] Training with 1200 samples, 87 features
# [2026-02-14 14:40:00] Fold 1: AUC=0.6720, LogLoss=0.3850
# ...
```

### 3. バックテスト実行

```bash
# 2年分のバックテスト
python -m app.cli backtest --start 2023-01-01 --end 2025-12-31

# カスタム予算でテスト
python -m app.cli backtest --start 2023-01-01 --end 2025-12-31 --budget 5000
```

**期待される出力**:
```
==================================================
Backtest Results:
  Events: 104
  Hits: 3 (2.9%)
  Total Cost: ¥1,040,000
  Total Payout: ¥1,200,000
  Profit: ¥160,000
  ROI: 15.4%
==================================================
```

### 4. Win5 予想

```bash
# 日曜日の Win5 を予想
python -m app.cli predict --date 2026-02-15 --budget 10000

# カスタム予算
python -m app.cli predict --date 2026-02-15 --budget 5000
```

### 5. ダッシュボード起動

```bash
# ダッシュボード起動
python -m app.cli dashboard

# ブラウザで自動開発（または手動で http://localhost:8501 にアクセス）
# ポート変更
python -m app.cli dashboard --port 8502
```

---

## トラブルシューティング

### 問題 1: `ModuleNotFoundError: No module named 'lightgbm'`

**原因**: 依存パッケージがインストールされていない

**解決**:
```bash
# 仮想環境が有効か確認
which python  # macOS/Linux
where python  # Windows

# 再インストール
pip install -r requirements.txt --force-reinstall
```

### 問題 2: `Permission denied` (Linux/macOS)

**原因**: ファイル権限がない

**解決**:
```bash
chmod +x src/app/cli.py
chmod +x tests/test_phase*.py
```

### 問題 3: `Database is locked`

**原因**: 複数プロセスが同時に DB にアクセス

**解決**:
```bash
# 既存プロセスを確認
ps aux | grep python

# プロセスを終了
kill <PID>

# DB ファイルをバックアップして削除
mv data/win5.db data/win5.db.backup
# 次回実行時に自動再作成
```

### 問題 4: スクレイピングが遅い

**原因**: ネットワーク遅延またはレート制限

**解決**:
```bash
# キャッシュ無効で強制取得
python -m app.cli collect --start ... --end ... --no-cache

# REQUEST_INTERVAL_SEC を増やす
# src/config/settings.py の REQUEST_INTERVAL_SEC を編集（例: 2.0 秒）
```

### 問題 5: メモリ不足

**症状**: `MemoryError` またはシステムがフリーズ

**解決**:
```bash
# 期間を短くして実行
python -m app.cli train --start 2024-01-01 --end 2024-12-31

# またはタスクマネージャで他のアプリを閉じる

# 物理メモリ不足の場合は RAM 増設検討
```

### 問題 6: Streamlit ポートが既に使用中

**原因**: 別プロセスがポート 8501 を使用

**解決**:
```bash
# 別のポートで起動
python -m app.cli dashboard --port 8502

# または既存プロセスを終了
# Windows
netstat -ano | findstr :8501
taskkill /PID <PID> /F

# macOS/Linux
lsof -i :8501
kill <PID>
```

---

## 運用ガイド

### 定期メンテナンス

```bash
# 週1回：データ更新
python -m app.cli collect --start $(date -d "7 days ago" +%Y-%m-%d) --end $(date +%Y-%m-%d)

# 月1回：モデル再学習
python -m app.cli train --start $(date -d "3 months ago" +%Y-%m-%d) --end $(date +%Y-%m-%d)

# 3ヶ月ごと：全体バックテスト
python -m app.cli backtest --start 2023-01-01 --end $(date +%Y-%m-%d)
```

### ログ監視

```bash
# データ収集ログ確認
tail -100 collect.log

# モデル学習ログ確認
python -m app.cli train ... 2>&1 | tee train.log

# 予想結果ログ確認
python -m app.cli predict ... 2>&1 | tee predict.log
```

---

## 推奨ワークフロー

### 日当たり
1. ✅ ダッシュボード起動して統計確認
   ```bash
   python -m app.cli dashboard &
   ```

2. ✅ 日曜朝に Win5 予想を実行
   ```bash
   python -m app.cli predict --date $(date +%Y-%m-%d) --budget 10000
   ```

### 月当たり
1. ✅ 月初にモデルを再学習
   ```bash
   python -m app.cli train --start ...
   ```

2. ✅ 月末に月間成績を確認
   ```bash
   python -m app.cli backtest --start ... --end $(date +%Y-%m-%d)
   ```

### 四半期
1. ✅ 全期間のバックテストで検証
2. ✅ 特徴量の重要度を再確認
3. ✅ 必要に応じて設定を調整

---

## 次のステップ

セットアップが完了したら：

1. **README.md** を確認
   ```bash
   cat README.md
   ```

2. **ドキュメント** を熟読
   - [FINAL_PROJECT_REPORT.md](./FINAL_PROJECT_REPORT.md)
   - [PHASE4_MODEL_REPORT.md](./PHASE4_MODEL_REPORT.md)
   - [PHASE6_ANALYSIS_REPORT.md](./PHASE6_ANALYSIS_REPORT.md)

3. **テスト実行** で動作確認
   ```bash
   pytest tests/ -v
   ```

4. **小規模データ** でテスト実行
   ```bash
   python -m app.cli collect --start 2024-01-01 --end 2024-03-31
   python -m app.cli train --start 2024-01-01 --end 2024-02-29
   python -m app.cli backtest --start 2024-01-01 --end 2024-03-31
   ```

5. **本データ** で本番運用開始
   ```bash
   python -m app.cli collect --start 2015-01-01 --end 2025-12-31 &
   ```

---

## サポート

問題が発生した場合：

1. **ログを確認**
   ```bash
   tail -50 collect.log
   tail -50 train.log
   ```

2. **ドキュメント検索**
   - `FINAL_PROJECT_REPORT.md` の「既知の制限事項」
   - 各 PHASE レポートのトラブルシューティング

3. **GitHub Issue を作成**
   - https://github.com/yuichi4107-lab/ClaudeCode/issues

---

**セットアップ完了後、すぐに運用を開始できます！**

Happy Betting! 🏇

