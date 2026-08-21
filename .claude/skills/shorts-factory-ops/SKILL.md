---
name: shorts-factory-ops
description: shorts-factory のローカル正本、非同期Driveミラー、生成・Telegram承認・4媒体自動投稿・重複動画/二重投稿の障害対応を行う専用運用スキル。動画被り、Claude CLI未ログイン、Driveミラー遅延、Telegram操作パネル不応答、SNS投稿失敗、posting ledger復旧、Seedance 2.0 AI動画背景生成の失敗・予算超過・フォールバック確認を扱う。
---

# shorts-factory 運用スキル

## 使う場面

このスキルは、`shorts-factory` の日次ショート動画生成と自動投稿で以下が起きた時に使う。

- 同じ動画・同じ台本・同じタイトルが連続して生成された
- 生成が失敗し、Claude CLI / フォールバック台本 / Driveロックが疑われる
- Telegram承認ボタンが反応しない、または承認前に投稿された
- X / Instagram / TikTok / YouTube の投稿失敗、部分失敗、二重投稿リスクがある
- runtime `~/shorts-factory/` とDriveミラーの反映差分・遅延を確認したい

shorts-factory の投稿は `shorts-factory/src/platforms/poster.py` による専用パイプライン（Telegram承認→自動投稿）であり、`post-sns` スキルの単発投稿スクリプト（`post_to_x.py` / `post_to_meta.py`）とは別系統。shorts-factory生成動画の単発re-postなど通常投稿は本スキルの対象外で、その場合はpost-snsを使う。

## 最初に見るもの

1. `.company/secretary/HANDOFF.md`
2. `.company/secretary/todos/` の最新日付TODO
3. `cd ~/shorts-factory/app && ~/shorts-factory/.venv/bin/python scripts/check_runtime_health.py --json`
4. `~/Library/Logs/shorts-generate.log` と `~/Library/Logs/shorts-approval.log`
5. runtime正本の `~/shorts-factory/state/queue/<queue_id>.json` と `~/shorts-factory/state/topics.json`
6. runtime正本の `~/shorts-factory/outputs/<queue_id>/`、`work/<queue_id>/`、`posting_ledger/<queue_id>.json`
7. `~/shorts-factory/drive_mirror/status.json` と、必要な時だけ `~/Library/Logs/shorts-drive-mirror.log`
8. Drive側 `.company/marketing/shorts-factory/` / `.company/outputs/shorts-factory/` は最後にミラーコピーとして確認する

Drive上のoutputsを広く走査するとGoogle Drive File Providerのロックを誘発しやすい。生成・承認・投稿・復旧判断はruntimeローカルだけを正にし、Driveミラーの異常は別障害として切り分ける。

## 2026-07-16 ローカル正本＋非同期Driveミラー

生成・Telegram承認・投稿のホットパスにDriveを入れない。

| 種別 | 正本 |
|---|---|
| queue / topics / outbox / pending rejection | `~/shorts-factory/state/` |
| outputs / work | `~/shorts-factory/outputs/` / `~/shorts-factory/work/` |
| 投稿成功ledger | `~/shorts-factory/posting_ledger/` |
| SNS認証 | `~/shorts-factory/sns_credentials/.env`（mode `0600`） |
| Driveミラー状態 | `~/shorts-factory/drive_mirror/status.json` |

Drive側のqueue/topics/outputs/ledgerは共有用コピーであり、手編集してもruntimeへ自動importされない。通常の一方向はローカル→Driveだけで、Drive側の手編集は次のミラーで上書きされ得る。Driveからruntimeへのコピーは、初回または管理された再移行で `migrate_runtime_state.py` を明示実行した時だけ行う。

### 実装済み運用コマンド

```bash
cd ~/shorts-factory/app
PY=~/shorts-factory/.venv/bin/python

# 障害時の最初の診断。ローカルだけを検査し、NGなら終了コード1
$PY scripts/check_runtime_health.py --json

# 旧Drive状態からruntimeへの一方向移行。通常運用の同期には使わない
$PY scripts/migrate_runtime_state.py \
  --source-marketing "<Drive>/YNFactory-cc/.company/marketing/shorts-factory"

# SNS認証をruntimeローカルへ明示同期（atomic write、mode 0600）
$PY scripts/sync_runtime_credentials.py \
  --source "<Drive>/YNFactory-cc/.company/engineering/sns-credentials/.env"

# ローカル正本をDriveへ1回best-effortミラー
$PY scripts/mirror_to_drive.py
$PY scripts/mirror_to_drive.py --timeout 180
```

- `migrate_runtime_state.py` は移行markerがあれば再importしない。`--force` は既存のローカルqueue/topicsを旧Drive状態から再構成する必要があると判断した管理作業だけに限定し、日常復旧では使わない
- `sync_runtime_credentials.py` は認証値を表示せずにruntimeへ同期する。通常の投稿処理はDrive認証ファイルを直接読まない
- `mirror_to_drive.py` はoutputsを先に、状態を後にコピーし、結果を `status.json` に残す。失敗時はbackoffし、runtime処理やSNS投稿を巻き戻さない。内部用 `--worker` を手動指定しない
- 4コマンドの実行自体はSNS投稿を行わない。ただしDriveへのミラー、runtime状態移行、認証更新という各コマンド本来のローカル/Drive変更は発生する

### 外部投稿の承認境界

- `auto_post: false` では、対象itemのTelegram **✅承認して投稿** が、設定済み媒体への初回投稿と同じitem内の設定済み自動retryに対する承認になる
- Telegram callback失敗、古い `approved`、診断・修復依頼は、新しい投稿承認ではない
- `retry_failed_posts.py --all` はdry-run。`--execute`、手動の再承認・再投稿、`auto_post: true` への変更、初回の実投稿は、実行直前にユーザーの明示承認を取る
- 投稿済みSNSの削除、公開状態変更、アカウント設定変更も、実行直前に別途明示承認を取る

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

`shorts-factory/src/video_bg_gen.py` がAtlas Cloud Seedance 2.0 APIを直接叩いてAI動画背景を生成する。実運用は配置済みruntime `~/shorts-factory/app` のコードを使い、コード更新時だけ `deploy.sh` で明示配置する。

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
3. runtime `~/shorts-factory/app/src/video_bg_gen.py` が意図したデプロイ版か確認する。生成中にDriveコードを自動同期する設計ではない
4. 実装の詳細技術知見は `.company/projects/shorts-factory/2026-07-07-seedance-atlas統合要件定義.md` を参照する

## 2026-07-08 ネタ帳自動補充ルール

発生した問題:

- `intermediate` のbacklogが0本になり、水曜14時・毎日19時の中級枠が beginner ネタへフォールバックした
- Telegramの「ネタが空です」「補充してください」通知は出るが、以前の実装では `topics.json` へ自動追記されなかった

以後の必須ルール:

- 生成前に対象難易度の使用可能ネタ数を確認する
- 使用可能ネタが `beginner < 8` / `intermediate < 16` なら自動補充する
- 補充後の目標は `beginner=18` / `intermediate=36`
- 自動補充候補はChatGPT単体に寄せず、Claude / Gemini / NotebookLM / Canva / Gamma / Make / Zapier などAIツール全般を含める
- 補充時も既存backlog・used・直近queueと類似するtopicは追加しない
- 手動確認は `~/shorts-factory/app/scripts/replenish_topics.py --difficulty intermediate` を使う
- ネタ帳の稼働状態はruntime正本 `~/shorts-factory/state/topics.json` で確認する。Driveミラー側の差分をruntimeへimportしない

## 2026-07-08 Seedance人物・テロップ固定ルール

発生した問題:

- 臨時AI動画で字幕の強調色が通常色と混ざり、テロップ色がバラバラに見えた
- Seedance台本が話者を自由に決めていたため、ユーザー要望の人物像と違う女性話者になった

以後の必須ルール:

- Seedance版の話者は「45歳の日本人男性、仕事のできそうなビジネスマン」に固定する
- 外見は短く整えた黒髪に少し白髪、清潔感のある顔、濃紺スーツ、白シャツ、濃色ネクタイを基本にする
- カット間で人物・年齢・髪型・服装・部屋・カメラ位置を変えない
- 女性、若い人物、カジュアル服、カットごとの衣装変更は生成前の台本検証で落とす
- AI動画の焼き込みテロップは通常/強調とも白ベースに統一し、カットごとに色を変えない
- Seedanceネイティブ日本語音声は外国語訛りが出るため、通常は使わない
- Seedance版の音声は `seedance.audio_mode: voicevox` でVOICEVOX男性話者（既定: 青山龍星）へ差し替える
- カメラはlocked-off / no zoom / no push-inを基本にし、カットごとの寄り引きを抑えて同一人物に見えやすくする
- 同一人物感が弱い場合は、次回生成前に「やや面長の顔・落ち着いた鋭い目・短い七三の黒髪・こめかみの白髪・清潔な髭なし」など、抽象的な年齢/性別だけでなく顔と髪の固定特徴をプロンプトへ入れる

## 実装済みガード

- `shorts-factory/src/script_gen.py`
  - `recent_duplicate_errors()` が直近タイトルと字幕/読み上げキューの同一性を検査する
  - `_recent_output_scripts()` はDriveではなく `CONFIG.work_dir` のruntime履歴を見る
  - フォールバック台本も重複検査で落とす
  - Claude CLI失敗時はstdout JSONを含め、ログイン失効などの理由を通知に出す
  - 英語ツール名・サービス名・英字略語は `display` 側で英字へ正規化し、読み上げ側はカタカナへ正規化する
  - Seedance版は45歳男性ビジネスマン固定条件を `validate_seedance_script()` で検査し、不一致なら再生成する

- `shorts-factory/scripts/run_generate.sh`
  - nvm配下の最新NodeをPATHへ追加し、launchd実行でも `claude` が動きやすくする
  - 配置済み `~/shorts-factory/app` だけを実行し、生成ホットパスでDriveコード同期を行わない

- `shorts-factory/src/platforms/poster.py`
  - 外部送信前に `~/shorts-factory/posting_ledger/` へ `attempting` をatomic保存し、成功後に媒体別投稿URLを `posted` として確定する
  - retry時はledgerに投稿済みURLがあれば外部投稿せずqueueへ復元する
  - `attempting` が残る、または送信結果が曖昧な時は `reconcile_required` で自動retryを止める

- `shorts-factory/src/approval_bot.py`
  - Telegram callback応答が失敗した場合は、承認/却下/保留の状態変更をしない
  - 古い `approved` item は自動再開しない
  - 一部媒体が投稿済みのitemは承認スキャンから再投稿しない
  - 移行時に残った `topics.json` の消費保留itemをruntime正本上で後続スキャンし、reconcileする
  - SNS別動画の復旧では `variant_group_id` / `consume_group_slug` を優先し、媒体別1本目ではなくグループ単位でネタ帳を使用済みにする
  - 復旧スキャンとTelegramプレビュー送信中にもwatchdog進捗を更新し、長い動画送信で10分ごとに再起動し続けない
  - Telegramプレビューの送信receiptが不明な時は自動再送せず、二重ボタンを防ぐ

- `shorts-factory/scripts/post_approved_item.py`
  - 承認後30分超過、または一部媒体投稿済みの `approved` item をworker側でもブロックする

- `shorts-factory/src/queue_lib.py` / `topic_store.py`
  - queue・topicsは `~/shorts-factory/state/` のローカル正本をatomic writeし、生成・承認・投稿中にDriveを読まない
  - `topic_store.replenish_topics()` が難易度別のネタ不足を自動補充し、生成前の `pipeline._select_topic_entry()` から呼ばれる

- `shorts-factory/src/drive_mirror.py` / `scripts/mirror_to_drive.py`
  - ローカル正本からDriveへの一方向コピーだけを担当する
  - 完成markerを各outputの最後にコピーし、サイズ・hashを検証する
  - timeout・lock・指数backoffでDrive停滞をruntimeホットパスから隔離する

## 復旧手順

### Driveロック・ミラー遅延が疑われる時

1. `check_runtime_health.py --json` を最初に実行する
2. healthがOKで `mirror.ok` だけがfalseなら、生成・承認・投稿は正常なままの可能性が高い。Driveコピー障害として切り分ける
3. `~/shorts-factory/drive_mirror/status.json` の `error` / `next_attempt_at` と `shorts-drive-mirror.log` を確認する
4. backoff中は待ち、必要ならbackoff後に `mirror_to_drive.py` を1回実行する。approval botや生成ジョブを先に再起動しない
5. Driveコピーのqueue/topicsを手編集・runtimeへimportしない。復旧確認はruntime正本→mirror status→Driveコピーの順で行う

### ローカルhealthがNGの時

1. `runtime migration is incomplete` は、初回移行かmarker欠損かを確認してから `migrate_runtime_state.py` を使う。既存runtimeがある状態で `--force` を先に使わない
2. `local SNS credentials missing or empty` / mode不正は、値を画面へ出さず `sync_runtime_credentials.py` で明示同期して再診断する
3. `deferred topic items remain` はruntime `state/queue/` と `state/topics.json` を調査し、Drive側を修正しない
4. `active local media missing` はruntime `work/` / `outputs/` / queueのlocal pathを確認する。Drive上に動画があるだけでは投稿可能と判定しない

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

1. runtime `state/queue/` のqueue item `platforms.*.status/url` を確認する
2. `~/shorts-factory/posting_ledger/<queue_id>.json` を確認する
3. ledgerに成功URLがある媒体は外部投稿せず、queueへURLを復元する
4. ledgerが `attempting` / `reconcile_required` の媒体は再投稿せず、各SNSの公開状態を照合する
5. `approved` のまま古いitemが残っていても、30分超過または一部投稿済みならworkerでブロックする

## 禁止事項

- 診断・修復依頼を外部投稿の承認と解釈しない。初回実投稿、手動再承認・再投稿、`retry_failed_posts.py --execute`、`auto_post: true` への変更は、実行直前のユーザー明示承認なしに行わない
- 投稿済みSNSの削除、公開状態変更、アカウント設定変更は、実行直前のユーザー明示承認なしに行わない
- 同一動画の疑いがあるitemを、確認なしに再承認・再投稿しない
- Driveミラー側のqueue/topics/outputs/ledgerを正本扱いせず、手編集内容をruntimeへ自動・手動で安易にimportしない
- Driveロックが出ている時にDrive outputsを広範囲に走査しない
- Telegram callback失敗を「承認済み」と扱わない

## 品質基準

- 英語ツール名・サービス名・英字略語はテロップで英字表記になり、読み上げだけカタカナになる
- テロップ修正後の差し替えでは、`script.json` だけでなく `subtitles.ass` と動画フレームも確認する
- 同一 `title` の直近再利用が生成段階で止まる
- 同一字幕/読み上げキューの動画が生成段階で止まる
- 生成失敗時のフォールバックでも重複検査を必ず通る
- 投稿済み媒体は自動再投稿・手動retryのどちらでも二重投稿されない
- 生成・承認・投稿はDrive File Providerが停止してもローカル正本で継続でき、ミラー失敗は独立して報告される
- Drive側の手編集はruntimeへ自動importされない
- ユーザーには「生成失敗」「重複検出」「投稿復旧」のどれが起きたかを分けて報告する
