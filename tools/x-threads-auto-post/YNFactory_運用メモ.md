# YNFactory 運用メモ

作成日: 2026-05-17

## 現状

この配布版は、通常運用では Google スプレッドシート + Google Apps Script を使う構成。

基本フロー:

1. note 記事から投稿文を作る
2. `X投稿` シートに予約行を入れる
3. GAS の `postNextScheduledItem()` が 30 分ごとに時刻到達済みの行を 1 件投稿する
4. 投稿 URL をシートに記録し、投稿済みにする

GitHub Actions 方式も残っているが、ドキュメント上は v1 バックアップ用。通常は GAS 方式を使う。

## 重要な注意点

### 1. サンプル投稿が過去日付

`skills/gas-x-post/Code.gs` の `setupSpreadsheet()` はサンプル投稿を 5 件入れる。
日付が `2026/3/23` と `2026/3/24` のため、2026-05-17 現在ではすべて投稿対象になる。

本番 API キーを入れて `setupTrigger()` を実行する前に、必ず以下のどちらかを行う。

- サンプル行を削除する
- サンプル行の `投稿済み` にチェックを入れる

### 2. エラー時も投稿済み扱いになり得る

現在の GAS は、X または Threads 投稿に失敗した場合も URL 欄に `エラー: ...` を書き込む。
その後、URL 欄が空でないことを理由に `投稿済み` が TRUE になる可能性がある。

運用では、投稿済みになっていても `X投稿URL` / `Threads投稿URL` が `エラー:` で始まっていないか確認する。
将来的には、エラー時は投稿済みにしない修正を入れると安全。

### 3. X API の料金体系は最新公式を確認

配布版 README には旧プラン名や金額の記載がある。
2026-05-17 に公式ドキュメントを確認した範囲では、X API は pay-per-usage / credit-based の説明になっている。
本番運用前に Developer Console の現在の料金表示を確認する。

参考:

- https://docs.x.com/x-api/getting-started/pricing
- https://docs.x.com/x-api/posts/manage-tweets/quickstart
- https://docs.x.com/fundamentals/authentication/oauth-1-0a/overview

### 4. ローカル Python のキュー方式は現状すぐ使えない

`queue/queue.json` が存在しないため、`dequeue_post.py --dry-run` はキューなしで終了する。
また Windows の標準文字コードでは、一部の記号出力で文字化けエラーが出る場合がある。

使う場合は、PowerShell で以下のように UTF-8 出力を指定すると確認できる。

```powershell
$env:PYTHONIOENCODING='utf-8'
python skills/note-to-x/scripts/dequeue_post.py --dry-run
```

ただし通常運用は GAS 方式で十分。

## .env 状態

値そのものは表示しない方針。

2026-05-17 確認時点:

- `API_KEY`: empty
- `API_KEY_SECRET`: empty
- `BEARER_TOKEN`: empty
- `ACCESS_TOKEN`: empty
- `ACCESS_TOKEN_SECRET`: empty
- `NOTE_USERNAME`: set
- `NOTE_SESSION_TOKEN`: set
- `POST_TONE`: set
- `MAX_POSTS_PER_DAY`: set
- `MIN_INTERVAL_MINUTES`: set
- `OUTPUT_DIR`: set

GAS 方式では `.env` ではなく、GAS のスクリプトプロパティに X API キーを入れる。

## 初回運用手順

1. Google スプレッドシートを新規作成する
2. Apps Script に `skills/gas-x-post/Code.gs` を貼り付ける
3. `setupSpreadsheet()` を実行する
4. 作成されたサンプル投稿 5 件を削除、または投稿済みにする
5. GAS のスクリプトプロパティに以下を設定する
   - `X_API_KEY`
   - `X_API_SECRET`
   - `X_ACCESS_TOKEN`
   - `X_ACCESS_TOKEN_SECRET`
   - Threads も使う場合のみ `THREADS_ACCESS_TOKEN`
6. まず `dryRun()` を実行し、意図した 1 行だけが対象になることを確認する
7. 本番前テスト用に、自分で作った短文 1 件だけを過去時刻で入れる
8. `postNextScheduledItem()` を手動実行して 1 件だけ投稿テストする
9. 成功したら `setupTrigger()` を実行して 30 分ごとの自動運用に入る

## 本番前チェックリスト

- [ ] サンプル投稿が削除済み、または投稿済みになっている
- [ ] 投稿内容に誤字・不要なURL・古い記事URLがない
- [ ] `X投稿する` / `Threads投稿する` のチェックが意図通り
- [ ] `投稿済み` は未チェック
- [ ] `dryRun()` で対象行が 1 件だけ表示される
- [ ] X API キーは投稿する本アカウントのもの
- [ ] X App Permissions は投稿可能な権限
- [ ] Access Token は権限変更後に再生成済み
- [ ] Threads は権限・アクセストークン期限を確認済み
- [ ] 投稿URL欄に `エラー:` が残っていない

## 次にやること

1. Google スプレッドシートを作成する
2. GAS に `Code.gs` を貼り付ける
3. `setupSpreadsheet()` まで実行する
4. サンプル行を削除する
5. X API キー取得・GASプロパティ設定へ進む

## note公開 -> X/Threads全自動連携

2026-05-17 追記。

`skills/gas-x-post/NoteRssBridge.gs` を追加した。
これは、note公開後のRSSを検知し、`note公開検知` シートに `pending_codex` として記録する追加GAS。
投稿文生成はOpenAI APIではなく、ChatGPT Proプラン内のCodexで行う。

詳細手順:

- `skills/gas-x-post/NOTE_RSS_BRIDGE_SETUP.md`
- `skills/gas-x-post/CODEX_PENDING_PROCESS_PROMPT.md`

運用フロー:

1. note記事を公開する
2. `pollNoteRssAndQueueSocialPosts()` がRSSで新着記事を検知する
3. `note公開検知` シートに `pending_codex` 行を追加する
4. Codexが記事を読み、X投稿3本・Threads投稿1本を生成する
5. Codexが `X投稿` シートに予約行を追加する
6. 既存の `postNextScheduledItem()` が予約時刻に投稿する

必要な追加スクリプトプロパティ:

- `NOTE_USERNAME` または `NOTE_RSS_URL`

初回は必ず `dryRunNoteRssBridge()` で対象記事を確認してから、`pollNoteRssAndQueueSocialPosts()` を手動実行する。
