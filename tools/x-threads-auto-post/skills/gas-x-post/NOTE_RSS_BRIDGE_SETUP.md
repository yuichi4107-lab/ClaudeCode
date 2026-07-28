# note公開検知 -> Codex処理待ち登録 セットアップ

この手順は、note記事を公開したあとにRSSで自動検知し、`note公開検知` シートへ記録するためのものです。
投稿文生成はChatGPT Proプラン内のCodexで行い、OpenAI APIやClaude APIは使いません。

## できること

1. noteのRSSを1時間ごとに確認
2. 新しく公開された記事だけを検知
3. `note公開検知` シートへ `pending_codex` として記録
4. Codexが `pending_codex` の記事を読み、X/Threads文を生成
5. Codexが既存の `X投稿` シートへ予約行を追加
6. 実際の投稿は既存の `postNextScheduledItem()` が実行

## 前提

先に通常のGASセットアップを完了してください。

- `Code.gs` をApps Scriptに貼り付け済み
- `setupSpreadsheet()` 実行済み
- `X投稿` シート作成済み
- サンプル投稿5件は削除済み、または投稿済み

## 追加するファイル

Apps Scriptに、以下の内容を追加します。

- `skills/gas-x-post/NoteRssBridge.gs`

既存の `Code.gs` の下にそのまま貼り足しても、別ファイルとして追加してもOKです。

## スクリプトプロパティ

Apps Scriptの「プロジェクトの設定」→「スクリプトプロパティ」に以下を設定します。

必須:

| プロパティ名 | 内容 |
|---|---|
| `NOTE_USERNAME` | noteのユーザー名。例: `your_name` |

または、`NOTE_USERNAME` の代わりに以下でもOKです。

| プロパティ名 | 内容 |
|---|---|
| `NOTE_RSS_URL` | note RSSのURL。例: `https://note.com/your_name/rss` |

既存投稿用:

| プロパティ名 | 内容 |
|---|---|
| `X_API_KEY` | X API Key |
| `X_API_SECRET` | X API Secret |
| `X_ACCESS_TOKEN` | X Access Token |
| `X_ACCESS_TOKEN_SECRET` | X Access Token Secret |
| `THREADS_ACCESS_TOKEN` | Threads投稿する場合のみ |

## 初回手順

1. `setupNoteRssBridge()` を実行
2. `dryRunNoteRssBridge()` を実行
3. ログでRSS URL、取得件数、未処理記事を確認
4. 問題なければ `pollNoteRssAndQueueSocialPosts()` を手動実行
5. `note公開検知` シートに `pending_codex` 行が追加されたことを確認
6. Codexでその行を処理し、`X投稿` シートへ予約行を追加
7. 問題なければ `setupNoteRssBridgeTrigger()` を実行

## 自動運用後の流れ

```text
note記事を公開
  ↓
最大1時間以内にRSS検知
  ↓
note公開検知シートに pending_codex で記録
  ↓
CodexがChatGPT Proプラン内で投稿文を生成
  ↓
CodexがX投稿シートに予約投入
  ↓
既存GASが予約時刻に投稿
```

予約時刻は、Codex側で検知時刻または処理時刻から調整します。

## 注意点

- noteの下書きは検知できません。検知対象は公開済み記事のみです。
- 初回実行時は、RSSに載っている最新記事が未処理として扱われます。
- 初回だけは `dryRunNoteRssBridge()` で対象記事を確認してから手動実行してください。
- GASは外部AI APIを呼びません。投稿文生成はCodex側で行います。
- RSS取得でエラーが出た場合、`note公開検知` シートの `エラー` 欄に記録されます。
- 完全自動にする場合は、Codex側の定期実行で `pending_codex` を処理します。

## Codex側の処理プロンプト

Codexで `pending_codex` を処理する際は、以下を使います。

- `skills/gas-x-post/CODEX_PENDING_PROCESS_PROMPT.md`
