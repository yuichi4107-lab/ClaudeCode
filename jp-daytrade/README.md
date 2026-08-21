# JP-DAYTRADE-v1 — 日本株デイトレシステム データ基盤

東証グロース市場の小型・材料銘柄を対象とした寄り前気配×板厚み戦略の実装。
工程0: データ基盤（J-Quants日足DB + kabu APIモック + 気配保存スクリプト）。

---

## セットアップ（5分で完了）

### 1. 環境構築

```bash
cd jp-daytrade
pip install -r requirements.txt
```

### 2. 設定ファイル作成

```bash
cp config/kabu_config.env.example config/.env
```

テキストエディタで `config/.env` を開き、J-Quants トークンを設定:
```
JQUANTS_REFRESH_TOKEN=your_refresh_token_here
```

### 3. DB 初期化

**Windows（推奨）**:
```bat
data\setup_db.bat
```

**Mac / Linux / Git Bash**:
```bash
bash data/setup_db.sh
```

### 4. 動作確認

```bash
# テスト実行（認証情報不要）
pytest tests/ -v

# kabu APIモック起動
python data/kabu_mock.py
# → http://localhost:18081/kabusapi/board/7203 でモック板情報を取得できる

# 気配保存テスト（モック使用）
python data/kabu_push_recorder.py --use-mock --no-time-window --symbols 7203
```

---

## J-Quants 認証情報設定手順

### 1. アカウント登録

1. [J-Quants 登録ページ](https://jpx.gitbook.io/j-quants-ja) でアカウント作成
2. Lightプラン（無料）を選択
3. メール認証完了

### 2. リフレッシュトークン取得

1. J-Quants ダッシュボードにログイン
2. 「トークン管理」→「リフレッシュトークン」を発行
3. コピーして `config/.env` に貼り付け:
   ```
   JQUANTS_REFRESH_TOKEN=eyJhbGciOi...（長い文字列）
   ```

### 3. 日足データ取得

```bash
python data/jquants_client.py fetch_all_growth
```

東証グロース全銘柄（約500銘柄）× 2年分を取得します（所要時間: 45〜60分）。

---

## kabu ステーション接続手順（Surface 用 / Phase 2以降）

### 前提条件
- 三菱UFJ eスマート証券の口座開設完了
- 信用取引口座開設 → Professional プラン自動適用
- Windows 版 kabu ステーションアプリのインストール

### 接続手順

1. Surface で kabu ステーションを起動・ログイン
2. 「設定」→「API」→「APIシステム設定」を有効化
3. API パスワードを設定
4. `config/.env` を更新:
   ```
   KABU_API_PASSWORD=your_api_password_here
   KABU_API_BASE_URL=http://localhost:18080
   ```
5. トークン取得テスト:
   ```bash
   python data/kabu_push_recorder.py --symbols 7203 9984
   ```

---

## ディレクトリ構成

```
jp-daytrade/
├── config/
│   ├── .env                     # 認証情報（gitignore対象）
│   └── kabu_config.env.example  # テンプレート
├── data/
│   ├── __init__.py
│   ├── jquants_client.py        # J-Quants APIクライアント
│   ├── kabu_mock.py             # kabu APIモックサーバー
│   ├── kabu_push_recorder.py    # 気配スナップショット保存
│   ├── universe_builder.py      # ユニバース候補リスト生成
│   ├── setup_db.sh              # DB初期化（Linux/Mac）
│   ├── setup_db.bat             # DB初期化（Windows）
│   ├── stocks_master.db         # 銘柄マスターDB（gitignore）
│   ├── daily_prices.db          # 日足価格DB（gitignore）
│   ├── quotes_live.db           # リアルタイム気配DB（gitignore）
│   └── schemas/
│       ├── stocks_master.sql
│       ├── daily_prices.sql
│       └── quotes_live.sql
└── tests/
    ├── test_jquants_client.py
    ├── test_kabu_mock.py
    ├── test_kabu_push_recorder.py
    └── test_universe_builder.py
```

---

## 値嵩株フィルター仕様

以下の条件いずれかを満たす銘柄を除外:

| 条件 | 閾値 |
|------|------|
| 株価 | > 3,000円 |
| 単元代金（株価 × 単元株数） | > 300,000円 |

境界値:
- 株価 2,999円 → 対象
- 株価 3,000円 → 対象（`>` のため）
- 株価 3,001円 → 除外
- 単元代金 300,000円 → 対象
- 単元代金 300,001円 → 除外

---

## トラブルシューティング

### 認証エラー: `JQuantsConfigError: J-Quants refresh tokenが未設定です`

**原因**: `config/.env` に `JQUANTS_REFRESH_TOKEN` が設定されていない

**対処**:
1. `config/.env` を確認
2. `JQUANTS_REFRESH_TOKEN=xxxxx` が正しく記載されているか確認
3. トークンの前後にスペースや引用符が入っていないか確認

### DB 初期化失敗

**原因**: スキーマファイルが見つからない

**対処**:
```bash
ls data/schemas/
# stocks_master.sql daily_prices.sql quotes_live.sql が存在するか確認
```

### kabu API 接続失敗: `KabuAPIError: kabu API トークン取得失敗`

**原因**:
- kabu ステーションが起動していない
- API パスワードが間違っている

**対処**:
1. kabu ステーションを起動してログイン
2. 設定 > API > APIシステム設定 が有効か確認
3. `config/.env` の `KABU_API_PASSWORD` を確認

開発・テスト時はモックを使用:
```bash
python data/kabu_push_recorder.py --use-mock --symbols 7203
```

### pytest が失敗する

```bash
# パスを確認してから実行
cd jp-daytrade
pytest tests/ -v --tb=short
```

---

## 開発状況

| 機能 | 状態 | 備考 |
|------|------|------|
| J-Quants クライアント | 実装済み（スケルトン） | 認証情報待ち |
| kabu API モック | 完成 | localhost:18081 |
| 気配保存（ポーリング） | 完成 | --use-mock でテスト可 |
| 気配保存（WebSocket） | スケルトン | 工程3で実装 |
| SQLite スキーマ | 完成 | 3テーブル |
| 値嵩株フィルター | 完成 | 境界値テスト済み |
| setup_db | 完成 | sh + bat 両対応 |

---

## ライセンス

本プロジェクトは個人利用目的のプライベートリポジトリです。
