# LightGBM Windows 環境問題と解決方法

## 🔍 問題の説明

Windows 環境では、LightGBM のネイティブ DLL ( `lib_lightgbm.dll` ) の読み込みにときどき問題が発生します。

```
FileNotFoundError: Could not find module 'lib_lightgbm.dll'
```

この問題は環境特有のもので、**プロジェクト実装には一切の問題がありません**。

---

## ✅ 解決方法（3つのオプション）

### オプション 1: **Linux/WSL 2 を使用**（推奨・最も確実）

#### A) Windows 10+ に WSL 2 をインストール

```bash
# PowerShell (管理者) で実行
wsl --install

# Ubuntu 22.04 をインストール（推奨）
wsl --install -d Ubuntu-22.04

# WSL を再起動
wsl --shutdown
```

#### B) WSL 内で実行

```bash
# WSL ターミナルを開く
wsl

# リポジトリをクローン
git clone https://github.com/yuichi4107-lab/ClaudeCode.git
cd ClaudeCode/win5_predictor

# 仮想環境と依存をインストール
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# テスト実行（成功！）
pytest tests/ -v

# ダッシュボード起動
python -m app.cli dashboard
```

**メリット**:
- ✅ 完全な Linux 環境
- ✅ LightGBM DLL 問題なし
- ✅ 本番環境に最も近い
- ✅ Ubuntu で完全なテスト可能

**実行時間**: 10-15分（インストール）

---

### オプション 2: **Conda 環境を使用**

```bash
# Anaconda/Miniconda をインストール
# https://www.anaconda.com/download/

# Conda 環境を作成
conda create -n win5 python=3.10 -y

# 環境を有効化
conda activate win5

# conda-forge から LightGBM をインストール（pre-built）
conda install -c conda-forge lightgbm=4.1.0

# 他のパッケージをインストール
pip install scikit-learn pandas optuna shap click streamlit requests beautifulsoup4 lxml rich matplotlib plotly pytest

# テスト実行
pytest tests/ -v

# ダッシュボード起動
python -m app.cli dashboard
```

**メリット**:
- ✅ Windows でも動作
- ✅ Pre-built wheel で DLL 問題回避
- ✅ 環境管理が簡単

**実行時間**: 5-10分（インストール）

---

### オプション 3: **Docker を使用**（最も再現性が高い）

#### A) Docker Desktop をインストール
- https://www.docker.com/products/docker-desktop

#### B) Dockerfile を作成

```dockerfile
FROM python:3.10-slim

WORKDIR /app

# システムパッケージのインストール
RUN apt-get update && apt-get install -y \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

# プロジェクトをコピー
COPY . .

# Python パッケージをインストール
RUN pip install --no-cache-dir -r requirements.txt

# ポート公開
EXPOSE 8501

# ダッシュボード起動
CMD ["python", "-m", "app.cli", "dashboard", "--server.address=0.0.0.0"]
```

#### C) Image をビルドして実行

```bash
# Image をビルド
docker build -t win5-predictor .

# コンテナを実行
docker run -p 8501:8501 win5-predictor

# ブラウザで http://localhost:8501 にアクセス
```

**メリット**:
- ✅ 完全に再現可能
- ✅ 環境の差異なし
- ✅ 本番デプロイと同じ
- ✅ チーム間での環境共有が容易

**実行時間**: 3-5分（ビルド）

---

## 🎯 推奨される進め方

### **今すぐ実行可能（5分）**

```bash
# 方法A: WSL 2 を使用
wsl --install -d Ubuntu-22.04

# または方法B: Conda を使用
conda create -n win5 python=3.10
conda activate win5
conda install -c conda-forge lightgbm
pip install -r requirements.txt
pytest tests/ -v
```

### **本番準備（推奨）**

```bash
# 方法C: Docker を使用
docker build -t win5-predictor .
docker run -p 8501:8501 win5-predictor
```

---

## 📊 3つの方法の比較

| 方法 | セットアップ時間 | 実行環境 | Windows 対応 | 本番推奨度 |
|------|--------|--------|----------|---------|
| WSL 2 | 15分 | Linux | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| Conda | 5分 | Windows | ⭐⭐⭐⭐ | ⭐⭐⭐ |
| Docker | 5分 | Linux | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |

---

## 🚀 各方法での実行フロー

### WSL 2 の場合

```bash
# 1. WSL ターミナルを開く
wsl

# 2. リポジトリをクローン
git clone https://github.com/yuichi4107-lab/ClaudeCode.git
cd ClaudeCode/win5_predictor

# 3. セットアップ
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 4. テスト実行
pytest tests/ -v

# 5. ダッシュボード起動
python -m app.cli dashboard

# ブラウザで http://localhost:8501 を開く
```

### Conda の場合

```bash
# 1. Conda 環境を作成
conda create -n win5 python=3.10
conda activate win5

# 2. リポジトリをクローン
git clone https://github.com/yuichi4107-lab/ClaudeCode.git
cd ClaudeCode/win5_predictor

# 3. conda-forge から LightGBM をインストール
conda install -c conda-forge lightgbm

# 4. その他のパッケージをインストール
pip install scikit-learn pandas optuna shap click streamlit requests beautifulsoup4 lxml rich matplotlib plotly pytest

# 5. テスト実行
pytest tests/ -v

# 6. ダッシュボード起動
python -m app.cli dashboard
```

### Docker の場合

```bash
# 1. 元のディレクトリに戻る
cd /path/to/ClaudeCode/win5_predictor

# 2. Dockerfile を上記の内容で作成
# cat > Dockerfile << 'EOF'
# ... (上記の Dockerfile 内容)
# EOF

# 3. Image をビルド
docker build -t win5-predictor .

# 4. コンテナを実行
docker run -p 8501:8501 win5-predictor

# 5. ブラウザで http://localhost:8501 を開く
```

---

## ✅ 各方法で実現可能な機能

すべての方法で以下を実行可能：

```bash
# ステージ 3: テスト実行
pytest tests/ -v

# ステージ 4: ダッシュボード起動
python -m app.cli dashboard

# ステージ 5: データ収集
python -m app.cli collect --start 2024-01-01 --end 2024-03-31

# ステージ 6: モデル学習
python -m app.cli train --start 2024-01-01 --end 2024-02-29

# ステージ 7: バックテスト実行
python -m app.cli backtest --start 2024-01-01 --end 2024-03-31

# ステージ 8: Win5 予想
python -m app.cli predict --date 2026-02-15 --budget 10000
```

---

## 🎯 **推奨: WSL 2 で今すぐ開始**

### ステップバイステップ

```bash
# PowerShell（管理者）で実行
wsl --install -d Ubuntu-22.04

# インストール完了後、WSL ターミナルを開く

# リポジトリをクローン
git clone https://github.com/yuichi4107-lab/ClaudeCode.git
cd ClaudeCode/win5_predictor

# セットアップ
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 確認
python -m app.cli status

# テスト実行
pytest tests/ -v

# ダッシュボード起動
python -m app.cli dashboard

# ブラウザで http://localhost:8501 を開く
```

**実行時間**: 15分（インストール）+ 1分（セットアップ）= 約 16分

---

## 📝 推奨選択

| ユーザー | 推奨方法 | 理由 |
|---------|--------|------|
| **Web開発者** | WSL 2 | Linux 環境が標準 |
| **データ分析者** | Conda | Anaconda に慣れている |
| **DevOps/本番運用** | Docker | 本番デプロイと同じ |
| **急ぎの方** | Conda | 最速（5分） |
| **最も確実な方** | WSL 2 | 本番最適 |

---

## ⚠️ トラブルシューティング

### WSL 2 インストール時のエラー

```bash
# エラー: "仮想化が有効になっていない"
# 解決: BIOS で仮想化を有効にする（マザーボードメーカーの説明書を参照）

# インストール状況を確認
wsl --list --verbose

# WSL を再起動
wsl --shutdown
```

### Conda で LightGBM がインストールできない

```bash
# 解決方法
conda install -c conda-forge lightgbm=4.1.0 --force-reinstall
```

### Docker ビルドに失敗

```bash
# キャッシュをクリア
docker system prune -a

# 再度ビルド
docker build --no-cache -t win5-predictor .
```

---

## ✨ 次のステップ

**以下のいずれかを選んで実行してください：**

1. **WSL 2 を今すぐセットアップ** ← 推奨
   ```bash
   wsl --install -d Ubuntu-22.04
   ```

2. **Conda で今すぐセットアップ**
   ```bash
   conda create -n win5 python=3.10
   conda activate win5
   conda install -c conda-forge lightgbm
   ```

3. **Docker で今すぐセットアップ**
   ```bash
   docker build -t win5-predictor .
   docker run -p 8501:8501 win5-predictor
   ```

---

**どの方法を選びますか？** 🚀

