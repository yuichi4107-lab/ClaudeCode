# NotebookLM YouTube 自動同期

指定 YouTube チャンネルの新規動画を、Playwright 経由で NotebookLM ノートブックに自動追加するツール。

> **現行構成（2026-06-06〜）: このMacで launchd 常駐 + CDP 接続方式**
> VPS の `storage_state` 静的注入方式は Google に bot 判定され、データセンターIPでセッションが
> 約2時間で失効したため廃止。**このMac（residential IP）上で「常駐 headless 実Chrome ＋ CDP接続」方式**へ移行した。
> 下記「Mac運用（現行）」が現行手順。さらに下の VPS 手順はレガシー/フォールバック参照用。

## Mac運用（現行）

### 構成
- **ランタイム**: `~/notebooklm-sync/`（**Google Drive外**。`.venv` / `.auth` / `state.sqlite` / `logs` / `secrets.yaml` を格納）
- **コード正本/バックアップ**: Drive上 `notebooklm-sync/`（runtime へ rsync で配布。secrets と runtime 成果物は除外）
- **認証**: 専用プロファイル `~/notebooklm-sync/.auth/chromium` に**実Chromeでログイン**。Playwright は自前で Chrome を起動せず、常駐 Chrome に **CDP接続**する（`cdp_endpoint: http://localhost:9222`）。※Playwright 起動の Chrome は headless/自動化フラグで Google に弾かれるため CDP 必須。
- **常駐Chrome**: launchd `com.ynfactory.notebooklm-chrome`（`scripts/start_chrome_mac.sh`、**headless** `--headless=new`・`--remote-debugging-port=9222`・`KeepAlive`・`RunAtLoad`）
- **同期ジョブ**: launchd `com.ynfactory.notebooklm-sync`（`.venv/bin/python src/sync.py`、WorkingDirectory=`~/notebooklm-sync`、`StartInterval=1800`＝30分毎）

### 初回ログイン / 再ログイン（セッション切れ時）
Telegram に `Google session expired` アラートが来たら:
1. 常駐Chromeを停止: `launchctl unload ~/Library/LaunchAgents/com.ynfactory.notebooklm-chrome.plist`
2. ログイン用Chrome起動: `bash ~/notebooklm-sync/scripts/login_mac.sh`（実Chromeが開く）
3. Googleにログイン → NotebookLM 表示を確認 → ウィンドウを閉じる
4. 常駐Chrome再開: `launchctl load ~/Library/LaunchAgents/com.ynfactory.notebooklm-chrome.plist`
5. 確認: `cd ~/notebooklm-sync && .venv/bin/python scripts/check_session.py` → `SESSION OK`

### 運用コマンド
| 目的 | コマンド |
|---|---|
| セッション確認 | `cd ~/notebooklm-sync && .venv/bin/python scripts/check_session.py` |
| 手動同期 | `launchctl start com.ynfactory.notebooklm-sync`（ログ: `logs/launchd-stdout.log` / `logs/sync.log`） |
| dry-run | `cd ~/notebooklm-sync && .venv/bin/python src/sync.py --dry-run` |
| 登録状況 | `launchctl list \| grep notebooklm` |
| 常駐Chrome再起動 | `launchctl kickstart -k gui/$(id -u)/com.ynfactory.notebooklm-chrome` |
| 通知テスト | `cd ~/notebooklm-sync && .venv/bin/python scripts/test_notify.py` |

### Telegram通知
専用ボット **@mnb121_bot**。`~/notebooklm-sync/secrets.yaml`（Drive外・git管理外）に `bot_token` / `chat_id`(=`8571447808`) を保存。失敗時アラート＋完了サマリを送信する。

---

## 前提条件

- Python 3.10 以上
- Playwright 対応環境（VPS: Ubuntu 22.04 推奨）
- Google アカウントへのログイン済み Chromium プロファイル（工程4で転送）
- Telegram bot token / chat_id（通知用。未設定でも動作可）

---

## セットアップ手順

### 1. リポジトリ配置

```bash
git clone <repo_url> /opt/notebooklm-sync
cd /opt/notebooklm-sync
```

### 2. 仮想環境と依存パッケージ

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
playwright install-deps chromium   # 初回のみ（root権限が必要な場合あり）
```

### 3. 設定ファイル

```bash
cp config.yaml.example config.yaml
cp secrets.yaml.example secrets.yaml
```

`config.yaml` を編集して `channel_id` と `notebook_id` を設定する。  
`secrets.yaml` に Telegram の `bot_token` と `chat_id` を設定する。

### 4. チャンネルの追加方法

`config.yaml` の `channels` リストにエントリを追加するだけでよい。コード変更は不要。

```yaml
channels:
  - id: UC_NEW_CHANNEL_ID
    handle: "@new_channel"
    name: "New Channel Name"
    notebook_id: ""  # NotebookLM URLから取得
```

---

## 認証情報の作成（ローカル → VPS 転送）

NotebookLM は公式 API を持たないため、ローカルで Google にログインして取得した Playwright `storage_state.json`（Cookie + LocalStorage）を VPS に転送して使用する。`storage_state` は OS 非依存のため Windows ローカル → Linux VPS でそのまま使える。

### ローカルで認証情報を作成

```bash
# ローカル（Windows/Mac）で実行
cd /path/to/notebooklm-sync
python -m venv .venv
.venv/Scripts/Activate.ps1   # PowerShell の場合
# source .venv/bin/activate   # bash の場合
pip install playwright PyYAML
playwright install chromium
python scripts/setup_auth.py
```

ブラウザが起動するので、Google アカウントでログインして NotebookLM が表示されたらターミナルで Enter を押す。`.auth/chromium/storage_state.json` が生成される。

### VPS へ転送

```bash
scp .auth/chromium/storage_state.json user@<VPS_IP>:/opt/notebooklm-sync/.auth/chromium/storage_state.json
ssh user@<VPS_IP> "chmod 600 /opt/notebooklm-sync/.auth/chromium/storage_state.json"
```

### notebook_id の取得

NotebookLM でノートブックを開き、URL からIDを取得する。

```
https://notebooklm.google.com/notebook/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
                                        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
                                        この部分が notebook_id
```

取得した `notebook_id` を `config.yaml` の対応チャンネルに記入する。

---

## 実行方法

```bash
cd /opt/notebooklm-sync
source .venv/bin/activate

# 初回: 全動画を取得して未処理のみ追加
python src/sync.py --init

# 通常: RSSで差分取得（新規動画のみ追加）
python src/sync.py

# 特定チャンネルのみ処理
python src/sync.py --channel UCRxPq02pjQS_ax60gcTSDHQ

# ドライラン（追加せず候補を確認）
python src/sync.py --dry-run

# ヘルプ
python src/sync.py --help
```

---

## 通知テスト方法

`secrets.yaml` に `bot_token` / `chat_id` を記入した後、以下のコマンドで送信確認できる。

```bash
cd /opt/notebooklm-sync    # VPS の場合
source .venv/bin/activate

# サマリ + アラートの両方を送信（引数なし）
python scripts/test_notify.py

# サマリのみ送信
python scripts/test_notify.py --summary

# アラートのみ送信
python scripts/test_notify.py --alert
```

`secrets.yaml` が未設定（bot_token / chat_id が空）の場合はTelegramへの送信を試みず、
設定方法の案内を表示して終了する。

---

## cron 設定例

```bash
crontab -e
```

```cron
# 毎時0分に差分同期を実行
0 * * * * cd /opt/notebooklm-sync && /opt/notebooklm-sync/.venv/bin/python src/sync.py >> logs/sync.log 2>&1
```

---

## トラブルシューティング

### Session Expired（Google ログアウト）

**症状:** ログに `Google session expired` / Telegram に ALERT が届く

**対処:**
1. ローカルで `python scripts/setup_auth.py` を再実行し、Google に再ログインする
2. `storage_state.json` を VPS へ再転送する

```bash
scp .auth/chromium/storage_state.json user@<VPS_IP>:/opt/notebooklm-sync/.auth/chromium/storage_state.json
```

### NotebookLM UI 変更（ボタンが見つからない）

**症状:** ログに `result=error reason=timeout` または `reason=TimeoutError`

**対処:**
1. `src/notebooklm.py` の上部セレクタ定数（`SEL_*`）を確認する
2. ブラウザの開発者ツールで新しいセレクタを特定し、定数を更新する

```python
# src/notebooklm.py 上部のセレクタ定数を編集
SEL_ADD_SOURCE_BUTTON = "..."
SEL_URL_INPUT_OPTION  = "..."
SEL_URL_TEXT_INPUT    = "..."
SEL_INSERT_CONFIRM    = "..."
```

### yt-dlp 失敗

**症状:** `list_all_videos failed after N attempts`

**対処:** yt-dlp を最新版に更新する

```bash
source .venv/bin/activate
pip install -U yt-dlp
```

### ログの確認

```bash
tail -f logs/sync.log
```

---

## ディレクトリ構成

```
notebooklm-sync/
├── config.yaml           # チャンネル・動作設定（git管理対象）
├── config.yaml.example   # 設定雛形
├── secrets.yaml          # Telegram認証情報（git管理外）
├── secrets.yaml.example  # secrets阛形
├── requirements.txt
├── .gitignore
├── README.md
├── src/
│   ├── sync.py           # メインエントリ
│   ├── youtube.py        # yt-dlp / feedparser ラッパ
│   ├── notebooklm.py     # Playwright操作
│   ├── state.py          # SQLite管理
│   ├── notify.py         # Telegram通知
│   └── config.py         # 設定ローダ
├── tests/
│   └── test_state.py     # SQLite冪等性テスト
├── .auth/                # Chromiumプロファイル（git管理外）
├── logs/                 # ログ（git管理外）
└── state.sqlite          # 処理済み動画DB（git管理外）
```
