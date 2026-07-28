# セットアップ状況

最終確認日: 2026-05-17

## 完了済み

- Codex Pro運用方針への切り替え
- note RSS検知用GAS `skills/gas-x-post/NoteRssBridge.gs` の追加
- Codex処理プロンプト `skills/gas-x-post/CODEX_PENDING_PROCESS_PROMPT.md` の追加
- Codex Pro運用ガイド `docs/codex-pro-workflow.md` の追加
- Google Sheets雛形CSVの追加
  - `docs/sheet-template-X投稿.csv`
  - `docs/sheet-template-note公開検知.csv`
- READMEにYNFactory版Codex Pro運用を追記
- GAS構文チェック完了

## 現在の設計

```text
note公開
  ↓
GASがnote RSSを検知
  ↓
note公開検知シートに pending_codex として記録
  ↓
CodexがChatGPT Pro内で投稿文を生成
  ↓
CodexがX投稿シートへ予約投入
  ↓
GASがX/Threadsへ投稿
```

## こちらで完了できなかった外部設定

Google Driveコネクタでスプレッドシート作成とCSVアップロードを試したが、どちらも `403 Forbidden` で失敗。
この接続にはGoogle Driveへの新規作成権限がない。

そのため、Googleスプレッドシートの作成とApps Scriptへの貼り付けは、以下のどちらかが必要。

1. ユーザーがGoogle Drive/Sheetsの作成権限を再接続する
2. ユーザーが手動でGoogleスプレッドシートを作成し、URLをCodexに渡す

## まだ必要な外部情報

- GoogleスプレッドシートURL
- `NOTE_USERNAME` または `NOTE_RSS_URL`
- X APIキー一式
  - `X_API_KEY`
  - `X_API_SECRET`
  - `X_ACCESS_TOKEN`
  - `X_ACCESS_TOKEN_SECRET`
- Threads投稿も行う場合
  - `THREADS_ACCESS_TOKEN`

## 次に実行すること

1. Googleスプレッドシートを作成
2. Apps Scriptに以下2ファイルを貼る
   - `skills/gas-x-post/Code_minimal.gs`（貼り付けやすい短縮版。推奨）
   - `skills/gas-x-post/NoteRssBridge.gs`
3. GASスクリプトプロパティに必要値を設定
4. `setupSpreadsheet()` 実行
5. サンプル投稿5件を削除
6. `setupNoteRssBridge()` 実行
7. `dryRunNoteRssBridge()` 実行
8. `pollNoteRssAndQueueSocialPosts()` 手動実行
9. `pending_codex` が出たらCodexで処理
10. 問題なければトリガーを有効化
