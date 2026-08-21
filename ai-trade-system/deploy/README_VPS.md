# ConoHa VPS セットアップ手順 - FX Forward Test

## 前提条件

- VPS に Python 3.11+ がインストール済み
- `/opt/ai-trade-system/` にプロジェクトが展開済み（`deploy.py` 実行後）
- `.env` に Saxo 認証情報が設定済み

---

## 1. systemd サービスの登録・起動

### サービスファイルをコピー

```bash
cp /opt/ai-trade-system/deploy/ai-trade-forward.service /etc/systemd/system/
```

### systemd に登録して起動

```bash
# デーモンを再読み込み
systemctl daemon-reload

# サービスを有効化（OS 再起動後も自動起動）
systemctl enable ai-trade-forward

# サービスを起動
systemctl start ai-trade-forward

# 起動状態を確認
systemctl status ai-trade-forward
```

### 起動ログの確認

```bash
journalctl -u ai-trade-forward -n 50 --no-pager
```

---

## 2. crontab 設定（トークンチェック 毎朝 8:00 JST）

JST 8:00 = UTC 23:00（前日）なので、UTC で設定する。

```bash
crontab -e
```

以下の行を追加:

```
# Saxo トークン有効期限チェック: 毎朝 8:00 JST (= UTC 23:00)
0 23 * * * /usr/bin/python3 /opt/ai-trade-system/scripts/check_saxo_token.py >> /opt/ai-trade-system/logs/forward/cron.log 2>&1
```

crontab の保存後、設定を確認:

```bash
crontab -l
```

---

## 3. ログの確認方法

### systemd ジャーナル（リアルタイム）

```bash
journalctl -u ai-trade-forward -f
```

### シグナルログ（JSONL形式）

```bash
# 本日のシグナルログを確認
cat /opt/ai-trade-system/logs/forward/signals_$(date +%Y%m%d).jsonl

# 最新 20 件を確認
tail -n 20 /opt/ai-trade-system/logs/forward/signals_$(date +%Y%m%d).jsonl
```

### アラートログ

```bash
cat /opt/ai-trade-system/logs/forward/alert.log
```

### cron 実行ログ

```bash
cat /opt/ai-trade-system/logs/forward/cron.log
```

### ローカルへのログ取得

開発PC から以下を実行:

```bash
# 本日分のログを取得
./scripts/fetch_logs.sh

# 指定日付のログを取得
./scripts/fetch_logs.sh 20260413

# 全ログを取得
./scripts/fetch_logs.sh all
```

---

## 4. トークン再取得手順

Saxo PAT（Personal Access Token）の有効期限は **24時間** です。
alert.log に `401 Unauthorized` のアラートが記録されたら、以下の手順でトークンを更新してください。

### 手順

1. [Saxo Developer Portal](https://www.developer.saxo/openapi/token/current) にアクセス
2. シミュレーション環境のトークンを発行（"Get Token" をクリック）
3. 発行されたトークンをコピー
4. VPS 上の `.env` を更新:

```bash
vi /opt/ai-trade-system/.env
# SAXO_SIM_TOKEN=<新しいトークンを貼り付け>
```

5. サービスを再起動:

```bash
systemctl restart ai-trade-forward
```

6. トークンチェックを手動実行して確認:

```bash
python3 /opt/ai-trade-system/scripts/check_saxo_token.py
```

---

## 5. サービスの停止・再起動

```bash
# サービスを停止
systemctl stop ai-trade-forward

# サービスを再起動
systemctl restart ai-trade-forward

# サービスの状態確認
systemctl status ai-trade-forward

# 自動起動を無効化
systemctl disable ai-trade-forward
```

---

## 6. ディレクトリ構成（VPS上）

```
/opt/ai-trade-system/
├── src/
│   ├── forward/          # フォワードテストモジュール
│   │   ├── forward_runner.py
│   │   ├── executor.py
│   │   ├── circuit_breaker.py
│   │   ├── scheduler.py
│   │   └── log_aggregator.py
│   ├── backtest/
│   └── trading/
├── scripts/
│   ├── check_saxo_token.py   # トークンチェック（cron用）
│   ├── fetch_logs.sh         # ログ取得（ローカルから実行）
│   └── report_forward.py     # レポート生成
├── deploy/
│   └── ai-trade-forward.service
├── logs/
│   └── forward/
│       ├── signals_YYYYMMDD.jsonl
│       ├── alert.log
│       └── cron.log
├── results/
│   └── fx_phase1/
│       └── portfolio_config.json
└── .env                  # 認証情報（git 管理外）
```

---

## 注意事項

- `.env` ファイルは `.gitignore` で除外されています。VPS へのデプロイ時は `deploy.py` が転送します
- Saxo PAT の有効期限は 24時間のため、毎日更新が必要です（将来的に OAuth フローへ移行予定）
- `--dry-run` モードで起動するため、実際の注文は発注されません
