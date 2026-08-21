# Sales OS VPS デプロイ手順

## 前提
- ConoHa VPS (163.44.101.31) に root でSSH可能
- `~/.ssh/config` に `Host yn-vps` エイリアス設定済み
- ConoHa VPS上に Python 3.10+ インストール済み（`/opt/keiba-unified/` の例を参考）

## 1. コード転送
```bash
# ローカル
cd g:/マイドライブ/YNFactory-cc
rsync -avz --exclude='.venv' --exclude='__pycache__' --exclude='tests' \
  --exclude='.pytest_cache' --exclude='data' \
  sales-ops/ yn-vps:/opt/sales-ops/
```

## 2. 依存セットアップ
```bash
ssh yn-vps "cd /opt/sales-ops && python3 -m venv venv && ./venv/bin/pip install -r requirements.txt"
```

## 3. 環境変数設定
```bash
ssh yn-vps "cd /opt/sales-ops && cp .env.example .env"
# 以下をVPS上で手動編集
# - ANTHROPIC_API_KEY（既存 .env から流用可）
# - GOOGLE_MAPS_API_KEY（Google Cloud Console で Places API New を有効化→API Key発行）
# - GMAIL_OAUTH_CLIENT_SECRET_JSON（Google Cloud Console で OAuth Client ID作成→JSONダウンロード→scp転送）
# - GMAIL_SENDER_ADDRESS=yuichi4107@gmail.com
# - SALES_OPS_DB_PATH=/opt/sales-ops/data/sales_ops.db
# - SALES_OPS_DRY_RUN=true   # 本番切替は実運用開始時のみ
```

## 4. OAuth 初回承認
OAuth は localhost リダイレクトが必要なため、**初回だけローカル（PC）で実行** → 生成された `token.json` をVPSに scp する:

```bash
# ローカル
cd sales-ops
python scripts/gmail_oauth_setup.py
# → ブラウザで承認 → secrets/gmail_token.json 生成
scp secrets/gmail_token.json yn-vps:/opt/sales-ops/secrets/
scp secrets/gmail_client_secret.json yn-vps:/opt/sales-ops/secrets/
```

## 5. DB初期化
```bash
ssh yn-vps "cd /opt/sales-ops && ./venv/bin/python scripts/init_db.py"
```

## 6. 動作確認（dry-run）
```bash
ssh yn-vps "cd /opt/sales-ops && ./venv/bin/python scripts/run_list_builder.py"
ssh yn-vps "cd /opt/sales-ops && ./venv/bin/python scripts/run_personalizer.py"
# 承認はPC側で /sales-briefing スキル経由
ssh yn-vps "cd /opt/sales-ops && ./venv/bin/python scripts/run_send_approved.py"
```

## 7. crontab 登録
```bash
ssh yn-vps "crontab -l > /tmp/crontab.bak && cat >> /tmp/crontab.bak <<EOF
# Sales OS
0 2 * * * /opt/sales-ops/venv/bin/python /opt/sales-ops/scripts/run_list_builder.py >> /var/log/sales-ops.log 2>&1
30 2 * * * /opt/sales-ops/venv/bin/python /opt/sales-ops/scripts/run_personalizer.py >> /var/log/sales-ops.log 2>&1
EOF
crontab /tmp/crontab.bak"
```

※ `run_send_approved.py` はcron登録しない（朝セッションの承認後にPC→SSHで明示的に叩く）。

## 8. 本番切替チェックリスト
Phase 1 MVP の本番稼働前チェック:
- [ ] Gmail OAuth token 動作確認（VPSから実際に送信成功）
- [ ] `.env` の `SALES_OPS_DRY_RUN=false` に変更
- [ ] 初回は `SALES_OPS_DAILY_SEND_LIMIT=5` で様子見
- [ ] 特電法フッター（配信停止URL、事業者名）が表示されるか実物目視確認
- [ ] 3日連続で送信→返信状況を見て spam 判定されていないかチェック
- [ ] 問題なければ `SALES_OPS_DAILY_SEND_LIMIT=30` → `50` → `100` と段階的に引き上げ

## 9. 既知の注意点（JP-DAYTRADE教訓から）
- **DBは必ず `/opt/sales-ops/data/` 以下に置く**（Google Drive 配下禁止、同期干渉でDB破損）
- VPS上のログは `/var/log/sales-ops.log`、週1で `logrotate` 推奨
- Google Maps API は月$200 無料枠あり、超過監視を Billing アラートで設定
