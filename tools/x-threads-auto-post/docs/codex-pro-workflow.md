# Codex Pro運用: note公開 -> X/Threads予約投稿

この運用は、OpenAI APIやClaude APIを使わず、ChatGPT Proプラン内のCodexで投稿文生成を行う方式です。

## 全体像

```text
note記事を下書き保存
  ↓
人がnote上で確認して公開
  ↓
GASがnote RSSを定期チェック
  ↓
新着公開記事を note公開検知 シートへ pending_codex として記録
  ↓
Codexが pending_codex を処理
  ↓
CodexがX投稿3本・Threads投稿1本を生成
  ↓
Codexが X投稿 シートへ予約行を追加
  ↓
既存GASが予約時刻にX/Threadsへ投稿
```

## 必要なシート

同じGoogleスプレッドシート内に以下2シートを作ります。

1. `X投稿`
2. `note公開検知`

### X投稿

既存の `setupSpreadsheet()` で作成されます。

| 列 | 見出し |
|---|---|
| A | 投稿日 |
| B | 時 |
| C | 分 |
| D | 投稿内容 |
| E | X投稿する |
| F | Threads投稿する |
| G | 画像1URL |
| H | 画像2URL |
| I | 画像3URL |
| J | 画像4URL |
| K | 投稿済み |
| L | X投稿URL |
| M | Threads投稿URL |

### note公開検知

追加GAS `NoteRssBridge.gs` の `setupNoteRssBridge()` で作成されます。

| 列 | 見出し |
|---|---|
| A | 検知日時 |
| B | 記事ID |
| C | タイトル |
| D | URL |
| E | 公開日時 |
| F | 状態 |
| G | X予約数 |
| H | Threads予約数 |
| I | エラー |

## GASに貼るファイル

Apps Scriptに以下を貼り付けます。

1. `skills/gas-x-post/Code_minimal.gs`（貼り付けやすい短縮版。推奨）
2. `skills/gas-x-post/NoteRssBridge.gs`

## GASスクリプトプロパティ

note RSS検知に必要:

- `NOTE_USERNAME` または `NOTE_RSS_URL`

投稿に必要:

- `X_API_KEY`
- `X_API_SECRET`
- `X_ACCESS_TOKEN`
- `X_ACCESS_TOKEN_SECRET`
- `THREADS_ACCESS_TOKEN`（Threadsも投稿する場合のみ）

AI生成用のAPIキーは不要です。

## 初回セットアップ順

1. Googleスプレッドシートを新規作成
2. Apps Scriptに `Code_minimal.gs` を貼る
3. Apps Scriptに `NoteRssBridge.gs` を追加で貼る
4. `setupSpreadsheet()` を実行
5. 自動作成されたサンプル投稿5件を削除
6. `setupNoteRssBridge()` を実行
7. `dryRunNoteRssBridge()` を実行
8. `pollNoteRssAndQueueSocialPosts()` を手動実行
9. `note公開検知` に `pending_codex` が入ることを確認
10. Codexで `skills/gas-x-post/CODEX_PENDING_PROCESS_PROMPT.md` を使って処理
11. `X投稿` に予約行が入ることを確認
12. `setupTrigger()` でX/Threads投稿トリガーを開始
13. `setupNoteRssBridgeTrigger()` でnote RSS検知トリガーを開始

## Codex定期実行にする場合

Codexの自動実行には、以下の情報が必要です。

- GoogleスプレッドシートURL
- 実行頻度（例: 1時間ごと、朝昼夜など）
- 自動で予約投入してよいか、最初は確認付きにするか

実行内容は `skills/gas-x-post/CODEX_PENDING_PROCESS_PROMPT.md` の通りです。
