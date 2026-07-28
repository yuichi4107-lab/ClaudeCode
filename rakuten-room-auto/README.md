# 楽天ROOM自動投稿システム

Googleスプレッドシートの商品リストを読み取り、楽天ROOMへ自動投稿するシステムです。

## 方針

- 楽天ROOMアカウントは作成済み前提です。
- **自動承認モード（既定）**: シートに商品URLと紹介文を入れるだけで、定期実行時に 未投稿→承認待ち→承認済→投稿 まで自動で進みます。承認済にする前に商品URLの実在チェック（HTTP 400以上で要確認）と完了済みURLとの重複チェックを行います。
- **自動ネタ補充（既定）**: 残りネタ（未投稿・承認待ち・承認済）が閾値（既定5件）以下になったら、楽天デイリーランキングから実在商品を取得し、テンプレート紹介文付きで既定5件を「未投稿」として自動追加します。シート内の既存URLとは重複しません。ジャンル・件数は `config.yaml` の `replenish` で調整、`replenish.enabled: false` で無効化できます。
- **同一商品スキップ**: URLが違っても実質同じ商品（同ショップの型番違い、紹介文の類似度が閾値0.28以上）は、補充時・自動承認時・投稿直前の3段階で検出してスキップします。検出された行は「要確認」になります。誤検知だった場合はステータスを「承認」に戻せばそのまま投稿されます。
- 手動承認に戻す場合は `RAKUTEN_ROOM_AUTO_APPROVE=0` を設定します。その場合は `承認済` になっている行だけ投稿対象になります。
- 紹介文が空の行は自動承認されず `要確認` になります（LLM生成を有効化している場合は prepare 時に自動生成を試みます）。
- 認証情報、Chromeプロファイル、ログ、投稿台帳は `~/rakuten-room-auto/` に置き、リポジトリには保存しません。

## スプレッドシート列

既定では以下の列名を使います。別名にしたい場合は `config.yaml` の `sheet.columns` を変更してください。

| 用途 | 既定列名 |
|---|---|
| 商品URL | `商品URL` |
| 商品紹介文 | `紹介文` |
| 投稿状態 | `ステータス` |
| 投稿日時 | `投稿日時` |
| エラー | `エラー` |
| 試行回数 | `試行回数` |

投稿状態は `未投稿` → `承認待ち` → `承認済` → `処理中` → `完了` を基本にします。

## 初期セットアップ

```bash
mkdir -p ~/rakuten-room-auto/secrets ~/rakuten-room-auto/logs ~/rakuten-room-auto/data
cp rakuten-room-auto/config.example.yaml ~/rakuten-room-auto/config.yaml
cp rakuten-room-auto/.env.example ~/rakuten-room-auto/.env
python3 -m venv ~/rakuten-room-auto/.venv
~/rakuten-room-auto/.venv/bin/python -m pip install -U pip
~/rakuten-room-auto/.venv/bin/python -m pip install -r rakuten-room-auto/requirements.txt
```

`~/rakuten-room-auto/config.yaml` にスプレッドシートIDとシート名を入れます。

## Google Sheets認証

Google Cloud Consoleでデスクトップアプリ用OAuthクライアントJSONを作成し、以下に置きます。

```text
~/rakuten-room-auto/secrets/google-oauth-client.json
```

その後、初回だけOAuthを実行します。

```bash
source ~/rakuten-room-auto/.env
~/rakuten-room-auto/.venv/bin/python rakuten-room-auto/scripts/setup_google_oauth.py
```

OAuthが終わったら、シートの不足ヘッダーとステータス選択肢を整えます。

```bash
source ~/rakuten-room-auto/.env
~/rakuten-room-auto/.venv/bin/python rakuten-room-auto/scripts/setup_sheet.py
```

## 楽天ROOMログイン確認

専用Chromeを起動し、そのChromeで楽天ROOMへログインします。

```bash
rakuten-room-auto/scripts/start_chrome_room.sh
```

別ターミナルでセッション確認を実行します。

```bash
source ~/rakuten-room-auto/.env
PYTHONPATH=rakuten-room-auto/src ~/rakuten-room-auto/.venv/bin/python -m rakuten_room_auto check-session
```

`Yuichi` が見つからない場合は、別アカウントでログインしている可能性があります。

## 運用コマンド

候補行を見るだけ:

```bash
source ~/rakuten-room-auto/.env
PYTHONPATH=rakuten-room-auto/src ~/rakuten-room-auto/.venv/bin/python -m rakuten_room_auto preview --limit 5
```

残りネタが閾値以下ならランキングから自動補充する:

```bash
PYTHONPATH=rakuten-room-auto/src ~/rakuten-room-auto/.venv/bin/python -m rakuten_room_auto replenish
```

`未投稿` 行を `承認待ち` に移す:

```bash
PYTHONPATH=rakuten-room-auto/src ~/rakuten-room-auto/.venv/bin/python -m rakuten_room_auto prepare --limit 5
```

`承認待ち` 行を事前チェック（URL実在・重複・紹介文あり）して `承認済` に移す:

```bash
PYTHONPATH=rakuten-room-auto/src ~/rakuten-room-auto/.venv/bin/python -m rakuten_room_auto approve --limit 5
```

`承認済` の1件だけ投稿する:

```bash
PYTHONPATH=rakuten-room-auto/src ~/rakuten-room-auto/.venv/bin/python -m rakuten_room_auto run --limit 1
```

投稿画面まで到達するが送信しない確認:

```bash
PYTHONPATH=rakuten-room-auto/src ~/rakuten-room-auto/.venv/bin/python -m rakuten_room_auto run --limit 1 --dry-run
```

## 定期実行

launchdテンプレートは `launchd/` にあります。登録時に `~/rakuten-room-auto/app/` へ実行用コピーを同期し、12:00、20:00、22:00に実行します。各回とも既定では replenish→prepare→approve→run の順で動き、ネタ切れ時の自動補充とシートに追加された商品の自動承認を行ったうえで1件投稿します。専用Chromeが起動していない場合は、投稿ジョブが自動で起動します。

```bash
rakuten-room-auto/scripts/install_launchd.sh
```

このコマンドは定期投稿を有効にするため、1件テスト投稿に成功してから実行してください。

## AI紹介文生成

`config.yaml` の `llm.enabled` を `true` にすると、紹介文が空の行に対してAI生成を試みます。モデル名は `OPENAI_MODEL` または `llm.model` で指定してください。未設定または生成失敗時は `要確認` になり、投稿されません。

## エラー時の挙動

- ログイン切れ、CAPTCHA、追加認証、楽天側UI変更が疑われる場合は投稿を止めます。
- 失敗行は `エラー` 状態になり、短い理由を `エラー` 列へ書きます。
- 実行履歴は `~/rakuten-room-auto/data/post-ledger.jsonl` に追記されます。
