# Codex側 pending_codex 処理プロンプト

このプロンプトは、ChatGPT Proプラン内のCodexで `note公開検知` シートの `pending_codex` 行を処理するためのものです。
OpenAI APIやClaude APIは使いません。

## Codexへの依頼文

以下のGoogleスプレッドシートを確認してください。

- スプレッドシートURL: `ここにX投稿管理シートURLを入れる`
- 入力シート: `note公開検知`
- 出力シート: `X投稿`

やること:

1. `note公開検知` シートで `状態` が `pending_codex` の行を探す
2. 未処理行の `URL` のnote記事を読む
3. 記事内容からX投稿3本、Threads投稿1本を作る
4. `X投稿` シートへ予約行を追加する
   - X投稿3本: `X投稿する = TRUE`, `Threads投稿する = FALSE`
   - Threads投稿1本: `X投稿する = FALSE`, `Threads投稿する = TRUE`
   - `投稿済み = FALSE`
   - URL欄は空欄
5. 投稿時刻は、処理時刻から15分後を起点に以下で入れる
   - X1: +15分
   - Threads1: +45分
   - X2: +3時間15分
   - X3: +6時間15分
6. `note公開検知` シートの該当行を更新する
   - `状態 = queued_by_codex`
   - `X予約数 = 3`
   - `Threads予約数 = 1`
   - `エラー` は空欄

投稿文ルール:

- X投稿は各280字以内
- Threads投稿は500字以内
- note記事URLを必ず末尾に入れる
- 同じ切り口を繰り返さない
- 強すぎる煽り、断定、誇大表現を避ける
- 記事タイトルの単なるコピペではなく、読む理由が伝わる文にする

失敗時:

- `note公開検知` シートの `状態 = codex_error`
- `エラー` に理由を短く記録する

