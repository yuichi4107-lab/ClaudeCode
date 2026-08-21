---
name: shorts-factory-ops
description: shorts-factory の生成・Telegram承認・4媒体自動投稿・重複動画/二重投稿の障害対応を行う専用運用スキル。動画被り、Claude CLI未ログイン、Driveロック、Telegram操作パネル不応答、SNS投稿失敗、posting ledger復旧、Seedance 2.0 AI動画背景生成の失敗・予算超過・フォールバック確認を扱う。
---

# shorts-factory 運用スキル

## 使う場面

このスキルは、`shorts-factory` の日次ショート動画生成と自動投稿で以下が起きた時に使う。

- 同じ動画・同じ台本・同じタイトルが連続して生成された
- 生成が失敗し、Claude CLI / フォールバック台本 / Driveロックが疑われる
- Telegram承認ボタンが反応しない、または承認前に投稿された
- X / Instagram / TikTok / YouTube の投稿失敗、部分失敗、二重投稿リスクがある
- runtime `~/shorts-factory/app` とDrive正本 `shorts-factory/` の反映差分を確認したい

shorts-factory の投稿は `shorts-factory/src/platforms/poster.py` による専用パイプライン（Telegram承認→自動投稿）であり、`post-sns` スキルの単発投稿スクリプト（`post_to_x.py` / `post_to_meta.py`）とは別系統。shorts-factory生成動画の単発re-postなど通常投稿は本スキルの対象外で、その場合はpost-snsを使う。

## 最初に見るもの

1. `.company/secretary/HANDOFF.md`
2. `.company/secretary/todos/` の最新日付TODO
3. `~/Library/Logs/shorts-generate.log`
4. `~/Library/Logs/shorts-approval.log`
5. `.company/marketing/shorts-factory/queue/<queue_id>.json`
6. `.company/outputs/shorts-factory/<queue_id>/`
7. runtime側の `~/shorts-factory/work/<queue_id>/` と `~/shorts-factory/posting_ledger/<queue_id>.json`

Drive上のoutputsを広く走査するとGoogle Drive File Providerのロックで生成が止まりやすい。生成時の重複検知や復旧判断は、原則としてruntimeローカルの `~/shorts-factory/work/` と queue item を正にする。

## 2026-07-01 動画被り修正の登録内容

発生した問題:

- Claude CLI が未ログイン状態になり、台本生成が失敗した
- 生成失敗後のフォールバック台本が固定的な内容になり、過去動画と同じ `title` / subtitles / reading cue を再生成した
- その結果、2026-06-29 19:00 と 2026-06-30 09:00 で同一動画が並んだ

以後の必須ルール:

- フォールバック台本も通常台本と同じ重複検証に通す
- 直近タイトルと一致したら生成不合格にする
- 字幕・読み上げキューの正規化シグネチャが直近動画と一致したら生成不合格にする
- Claude CLIの確認は `claude auth status` だけでなく、非対話実行 `claude -p` まで通す
- `Not logged in - Please run /login` が出たら、動画を量産せずログイン復旧を先に行う
- 重複動画を見つけたら、後続の重複queueは `skipped` にし、Telegramボタンは無効化してから別テーマで再生成する

## 2026-07-02 英語ツール名テロップ修正の登録内容

発生した問題:

- `Canva` / `Gamma` / `NotebookLM` などの英語ツール名が、音声を安定させるためのカタカナ読みに引っ張られ、画面テロップにもカタカナで焼き込まれた
- 既存動画は字幕が焼き込み済みのため、`script.json` やプロンプトだけ直しても表示は変わらない

以後の必須ルール:

- 英語ツール名・サービス名・一般的な英字略語（PDFなど）は `display` では英字表記を維持する
- `tts_text` / `reading_kana` では読み上げ安定のためカタカナへ変換してよい
- 新しい英語ツール名を扱う時は、`src/script_gen.py` の表示正規化と `src/jp_text.py` の音韻比較読み辞書を同時に追加する
- テロップ表示修正後の差し替えでは、旧queueを `skipped` にしてTelegramボタンを外し、再レンダリング後に `subtitles.ass` と動画フレームで焼き込み表示を確認する

## 2026-07-07 Seedance 2.0（Atlas Cloud）AI動画背景統合

`shorts-factory/src/video_bg_gen.py`（Drive正本のみに存在。本ブラッシュアップ時点で runtime `~/shorts-factory/app` には未同期）が、Atlas Cloud Seedance 2.0 APIを直接叩いてAI動画背景を生成する。

- カット1はtext-to-video、カット2以降は前カットの最終フレームをstart_imageにしたimage-to-videoで連鎖生成し、人物・服装・部屋を統一する
- reference-to-video（顔画像参照）は権利保護フィルタで弾かれるため使用しない
- 全リクエストにUser-Agentヘッダーが必須（Cloudflareが標準UAを403で弾く）
- 生成動画URLは24時間で失効するため、completed直後に即ダウンロードする
- 失敗（failed/timeout/フィルタブロック）時は課金されない
- 秒単価: fast=$0.09/s、std=$0.112/s
- 月次予算上限は `config seedance.monthly_budget_usd`（コード上のデフォルトは130、要件定義書の試算は週5本運用で月$78〜117）。`shorts-factory/src/video_bg_gen.py` の `budget_remaining()` / `is_budget_available()` で予算超過時は生成をスキップする
- 適用枠は `config seedance.slots`（曜日-時、例 `mon-09` / `wed-14` / `fri-19` / `sat-14` / `sun-09` の週5枠）と実行時刻を `shorts-factory/src/pipeline.py` の枠判定ロジックで照合し、該当枠のみSeedance版、それ以外は従来の静止画カード版を使う
- コストログは `~/shorts-factory/logs/seedance_costs.jsonl`（`pipeline.py` が記録）
- 異常時（API失敗・予算超過・枠外）は静止画カード版へ自動フォールバックする

障害対応時の確認ポイント:

1. 週5枠以外の時間帯でSeedance版が使われていないか、`pipeline.py` の枠判定と `seedance_costs.jsonl` のタイムスタンプを突き合わせる
2. 月次コストが上限に近い場合は `budget_remaining()` の残額を確認し、超過ならフォールバックが機能しているか確認する
3. Drive正本の `shorts-factory/src/video_bg_gen.py` と runtime `~/shorts-factory/app` の同期状態を確認する（未同期だと本番では旧動作のまま）
4. 実装の詳細技術知見は `.company/projects/shorts-factory/2026-07-07-seedance-atlas統合要件定義.md` を参照する

## 実装済みガード

- `shorts-factory/src/script_gen.py`
  - `recent_duplicate_errors()` が直近タイトルと字幕/読み上げキューの同一性を検査する
  - `_recent_output_scripts()` はDriveではなく `CONFIG.work_dir` のruntime履歴を見る
  - フォールバック台本も重複検査で落とす
  - Claude CLI失敗時はstdout JSONを含め、ログイン失効などの理由を通知に出す
  - 英語ツール名・サービス名・英字略語は `display` 側で英字へ正規化し、読み上げ側はカタカナへ正規化する

- `shorts-factory/scripts/run_generate.sh`
  - nvm配下の最新NodeをPATHへ追加し、launchd実行でも `claude` が動きやすくする

- `shorts-factory/src/platforms/poster.py`
  - `~/shorts-factory/posting_ledger/` に媒体別投稿成功URLを保存する
  - retry時はledgerに投稿済みURLがあれば外部投稿せずqueueへ復元する

- `shorts-factory/src/approval_bot.py`
  - Telegram callback応答が失敗した場合は、承認/却下/保留の状態変更をしない
  - 古い `approved` item は自動再開しない
  - 一部媒体が投稿済みのitemは承認スキャンから再投稿しない
  - Driveロックで `topics.json` の消費が後回しになったitemを後続スキャンで復旧する
  - SNS別動画の復旧では `variant_group_id` / `consume_group_slug` を優先し、媒体別1本目ではなくグループ単位でネタ帳を使用済みにする
  - 復旧スキャンとTelegramプレビュー送信中にもwatchdog進捗を更新し、長いDrive I/Oや動画送信で10分ごとに再起動し続けない

- `shorts-factory/scripts/post_approved_item.py`
  - 承認後30分超過、または一部媒体投稿済みの `approved` item をworker側でもブロックする

- `shorts-factory/src/fs_retry.py` / `queue_lib.py` / `topic_store.py`
  - Google Drive File Provider がファイル読み込みで固まる場合に備え、queue読み込み・個別queue読み書き・`topics.json` 読み書きへ短時間タイムアウトを入れる
  - タイムアウトは一時I/Oエラーとして扱い、該当ファイルを読み飛ばしてapproval bot全体の停止を避ける

## 復旧手順

### Driveロック通知が出た時

1. 通知文が `ネタ帳更新だけ後回し` なら、生成とqueue登録は完了している。投稿失敗とは分けて扱う
2. 対象queueの `topic_store.consume_deferred_error` を確認する
3. `~/Library/Logs/shorts-approval.log` に `ネタ帳消費を復旧` が出ているか確認する
4. `approval_bot watchdog: 600秒応答なし` が連続している場合は、runtime `~/shorts-factory/app` に最新コードを同期し、`com.ynfactory.shorts-approval` を再起動する
5. 復旧後は `topics.json` で対象topicが `backlog` から外れ、`used` に入っていること、queueの `consume_deferred_error` が消えていることを確認する

### 同じ動画ができた時

1. queue itemの `id`、`title`、`topic`、`difficulty`、`review`、`platforms` を確認する
2. `final.mp4` のハッシュ、`script.json` の `title`、`topic`、`cues` を直近動画と比較する
3. 同一なら後続itemを `skipped` にし、`review.reason` に `duplicate_guard` を残す
4. Telegramの該当メッセージはボタンなし状態へ編集する
5. Claude CLIログインを確認し、別topicまたは別切り口で再生成する

### Claude CLIの状態確認

```bash
claude auth status
printf '{"ok": true}' | claude -p 'Return this JSON unchanged.'
```

2つ目が非対話で成功しない場合、launchdの生成では失敗しやすい。ログイン復旧後に再生成する。

### 投稿の二重実行が疑われる時

1. queue itemの `platforms.*.status/url` を確認する
2. `~/shorts-factory/posting_ledger/<queue_id>.json` を確認する
3. ledgerに成功URLがある媒体は外部投稿せず、queueへURLを復元する
4. `approved` のまま古いitemが残っていても、30分超過または一部投稿済みならworkerでブロックする

## 禁止事項

- 投稿済みSNSの削除、公開状態変更、アカウント設定変更は、ユーザーの明示承認なしに実行しない
- 同一動画の疑いがあるitemを、確認なしに再承認・再投稿しない
- Driveロックが出ている時にDrive outputsを広範囲に走査しない
- Telegram callback失敗を「承認済み」と扱わない

## 品質基準

- 英語ツール名・サービス名・英字略語はテロップで英字表記になり、読み上げだけカタカナになる
- テロップ修正後の差し替えでは、`script.json` だけでなく `subtitles.ass` と動画フレームも確認する
- 同一 `title` の直近再利用が生成段階で止まる
- 同一字幕/読み上げキューの動画が生成段階で止まる
- 生成失敗時のフォールバックでも重複検査を必ず通る
- 投稿済み媒体は自動再投稿・手動retryのどちらでも二重投稿されない
- ユーザーには「生成失敗」「重複検出」「投稿復旧」のどれが起きたかを分けて報告する
