# shorts-factory — 日本語ショート動画 全自動生成・自動投稿システム

テーマ（ネタ帳）→ 台本AI生成 → VOICEVOX音声 → 背景画像 → FFmpeg合成（字幕焼き込み）
→ 機械品質検証 → Telegram承認 → X / YouTube Shorts / Instagram Reels / TikTok 自動投稿。

**ランニングコスト0円構成**（claude CLI＋VOICEVOX＋whisper.cpp＋PILカード画像）。
APIキーを入れるとAI画像等にアップグレード可能。

## 字幕正確性の4層防御（本システムの核）

1. **生成層**: 台本JSONをスキーマ検証（1行≤13文字・読み仮名必須・字幕と読み上げ文のLCS包含≥70%）。違反は自動再生成
2. **合成層**: 字幕1行=TTS1チャンクで個別合成し、**wav実測長から字幕タイミングを機械確定**（ずれは構造上発生しない）。VOICEVOXの読み（audio_query kana）と台本読み仮名を突合し、乖離したらかな直読みへ自動切替。頻出AI用語はユーザー辞書登録（ChatGPT=チャットジィーピィーティィー等、Whisper実測で明瞭発音を選定）
3. **検証層**: 完成動画を whisper.cpp **large-v3-turbo** で逆文字起こし → 台本と**音韻ベース**（pykakasi読み化・数字/長音/濁点/促音の表記ゆれ折り畳み）で行単位CER突合。行CER≤0.20・平均≤0.10 で合格。不合格行はかな直読み再合成→再レンダリング（≤5ループ、進捗なしは早期打ち切り→blocked）
4. **仕様層**: ffprobe（1080x1920/h264+aac/尺/サイズ）・blackdetect・ebur128（-14LUFS）・字幕端点・プレビューフレーム3枚（Telegramで人間も目視）

## 日常運用

- 09:00 / 14:00 / 19:00 に自動生成 → 標準では有効媒体ごとに別動画を生成し、Telegram に媒体別プレビュー動画＋ボタンが届く
- 難易度バランスは 09:00=初級、14:00=中級、19:00=中級
- **✅承認して投稿** を押すと有効媒体へ自動投稿（結果URLが返ってくる）
- **❌却下** でスキップ、**⏸保留** で後回し
- ネタ帳は難易度別に自動補充される。使用可能ネタが初級8本未満 / 中級16本未満になると、重複チェック済み候補から初級18本 / 中級36本まで補充する
- **完全自動化**: 明示承認を得たうえで `~/shorts-factory/config.yaml` に `queue: {auto_post: true}` を設定する（承認スキップ・事後通知）

2026-06-16時点の実運用は、`~/shorts-factory/config.yaml` に
`queue.platforms: [x, youtube, instagram, tiktok]` を設定済み、`auto_post: false` の承認制。
YouTube / TikTok は専用Chromeプロファイルへのログイン確認後に実投稿可能になる。

## 2026-07-16 ローカル正本＋非同期Driveミラー

生成・Telegram承認・投稿のホットパスは、すべて `~/shorts-factory/` 配下のローカル状態を正本にする。Google Drive側は共有・閲覧・バックアップ補助のための**非同期ミラー**であり、稼働中のqueueやネタ帳の正本ではない。

| データ | runtime正本 |
|---|---|
| queue | `~/shorts-factory/state/queue/` |
| topics | `~/shorts-factory/state/topics.json` |
| 通知outbox / 却下待ち | `~/shorts-factory/state/notification_outbox/` / `~/shorts-factory/state/pending_rejections/` |
| 完成outputs | `~/shorts-factory/outputs/` |
| 作業中データ | `~/shorts-factory/work/` |
| 投稿成功ledger | `~/shorts-factory/posting_ledger/` |
| SNS認証 | `~/shorts-factory/sns_credentials/.env`（mode `0600`） |
| Driveミラー状態 | `~/shorts-factory/drive_mirror/status.json` |

Driveへの反映は `com.ynfactory.shorts-drive-mirror` が5分間隔でローカル→Driveへ行う。ミラー失敗や遅延は、生成・承認・投稿の失敗を意味しない。Drive側の `.company/marketing/shorts-factory/` や `.company/outputs/shorts-factory/` を手編集してもruntimeへは**自動importされず**、次のミラーでローカル正本に上書きされ得る。queue/topicsの修復はDrive側を編集せず、必ずruntime正本に対して行う。

## セットアップ（済んでいるもの）

> 新しいMacへ移設する場合: `python3.12 -m venv ~/shorts-factory/.venv && pip install -r requirements.txt`、
> `config.yaml.example`/`secrets.yaml.example` を `~/shorts-factory/` へコピーして編集、
> VOICEVOXエンジンとwhisperモデルを再取得（brew install whisper-cpp p7zip ffmpeg）。
> Playwrightは常駐Chrome(CDP)に接続するため `playwright install` は**不要**。

- venv: `~/shorts-factory/.venv`（python3.12 / openai, tweepy, playwright, pykakasi 等）
- VOICEVOX engine 0.25.2: `~/shorts-factory/voicevox/`（パイプラインがオンデマンド起動）
- whisper.cpp: `brew install whisper-cpp` + `~/shorts-factory/models/ggml-large-v3-turbo.bin`
- フォント: `assets/fonts/NotoSansJP-{Bold,Black}.otf`（OFL）
- 秘密情報: `~/shorts-factory/secrets.yaml`（Telegram=暫定で@mnb121_bot流用）。SNS認証のruntime正本は `~/shorts-factory/sns_credentials/.env`。Drive側からの更新は `sync_runtime_credentials.py` で明示同期する

## launchd 登録（初回）

```bash
cd "<Drive>/YNFactory-cc/shorts-factory/scripts" && ./deploy.sh install
```

| ジョブ | 役割 |
|---|---|
| com.ynfactory.shorts-generate | 09:00 / 14:00 / 19:00 に、配置済みの `~/shorts-factory/app` だけで生成 |
| com.ynfactory.shorts-approval | 承認デーモン常駐（Telegramボタン処理・投稿実行） |
| com.ynfactory.shorts-chrome | YouTube用 常駐Chrome（CDP 9223） |
| com.ynfactory.shorts-tiktok-chrome | TikTok用 常駐Chrome（CDP 9224） |
| com.ynfactory.shorts-drive-mirror | 5分間隔でローカル正本をDriveへbest-effortミラー |

`deploy.sh install` は初回に旧Drive状態の一方向移行とSNS認証の明示同期を行う。通常の生成ジョブはDriveからコードや状態を同期しない。コード更新時だけ `deploy.sh` を明示実行してruntime appを更新する。

## YouTube / TikTok 初回ログイン（人間作業）

```bash
launchctl unload ~/Library/LaunchAgents/com.ynfactory.shorts-chrome.plist
~/shorts-factory/app/scripts/login_youtube.sh   # Chromeが開く→Googleログイン→Studioが見えればOK
# Chromeを閉じて
launchctl load ~/Library/LaunchAgents/com.ynfactory.shorts-chrome.plist

launchctl unload ~/Library/LaunchAgents/com.ynfactory.shorts-tiktok-chrome.plist
~/shorts-factory/app/scripts/login_tiktok.sh    # Chromeが開く→TikTokログイン→Studio Uploadが見えればOK
# Chromeを閉じて
launchctl load ~/Library/LaunchAgents/com.ynfactory.shorts-tiktok-chrome.plist

~/shorts-factory/.venv/bin/python ~/shorts-factory/app/scripts/check_platforms.py
```

セッション失効時は Telegram に手順つきアラートが届く（投稿は blocked で保全）。

## 手動操作

```bash
cd ~/shorts-factory/app
PY=~/shorts-factory/.venv/bin/python
$PY -m src.pipeline                          # ネタ帳から1本生成→キュー→Telegram
$PY -m src.pipeline --difficulty intermediate # 中級ネタを明示生成
$PY -m src.pipeline --topic "..." --no-queue # テーマ指定・キュー登録なし（テスト）
$PY -m src.pipeline --topic "..." --target-platform instagram --no-queue # SNS別台本寄せのテスト
$PY -m src.pipeline --single-video           # 従来どおり1本の動画を有効媒体へ投稿するキューを作成
$PY scripts/replenish_topics.py --difficulty intermediate # ネタ帳の手動補充確認
$PY -m src.approval_bot                      # 承認デーモンを手動起動
```

### 状態移行・認証同期・ヘルスチェック・Driveミラー

```bash
cd ~/shorts-factory/app
PY=~/shorts-factory/.venv/bin/python

# 障害時は最初に実行。ローカル状態だけを診断し、NGなら終了コード1
$PY scripts/check_runtime_health.py --json

# 初回移行・管理された再移行だけ。旧Drive状態をruntimeへ一方向コピー
$PY scripts/migrate_runtime_state.py \
  --source-marketing "<Drive>/YNFactory-cc/.company/marketing/shorts-factory"

# Drive側の認証ファイルをruntimeへ明示同期（atomic write、mode 0600）
$PY scripts/sync_runtime_credentials.py \
  --source "<Drive>/YNFactory-cc/.company/engineering/sns-credentials/.env"

# ローカル正本をDriveへ1回ミラー。投稿処理は行わない
$PY scripts/mirror_to_drive.py
# 大きなoutputsを扱う時だけ監督タイムアウトを変更
$PY scripts/mirror_to_drive.py --timeout 180
```

`migrate_runtime_state.py` は通常運用の同期コマンドではない。移行済みならmarkerを返して何もしないため、`--force` を日常復旧で使わない。`--force` は既存のローカルqueue/topicsを旧Drive状態から再構成する必要があると判断した、管理された再移行時だけ使う。Driveを手編集してからmigrationを実行する運用は禁止する。

`mirror_to_drive.py` はローカル→Driveの一方向だけで、結果を標準出力と `~/shorts-factory/drive_mirror/status.json` に記録する。失敗時はbackoffし、runtime正本をDrive側へ戻したり、外部SNSへ投稿したりしない。内部用の `--worker` は手動運用で指定しない。

### 失敗媒体だけ自動再投稿・手動再試行

複数媒体投稿で一部だけ失敗した場合、標準では失敗媒体だけ最大2回まで自動再投稿する。
成功済み媒体は `posted` のまま保持され、自動再投稿・手動再試行のどちらでも二重投稿されない。
ただし、外部送信後のtimeoutなど「公開済みか判定できない失敗」は自動再投稿しない。queueとposting ledgerを `reconcile_required` にして停止し、公開状態を確認する。

自動再投稿後も残った場合、キュー全体は `partial_failed` または `failed` になり、Telegramの投稿結果に手動再試行コマンドが出る。

```bash
cd ~/shorts-factory/app
PY=~/shorts-factory/.venv/bin/python
$PY scripts/retry_failed_posts.py --all        # dry-run（外部投稿なし）
$PY scripts/retry_failed_posts.py <queue_id> --execute # 外部投稿。直前の明示承認が必要
```

自動再投稿の回数や待機秒数は `queue.retry_max_attempts` / `queue.retry_delay_sec` で変更できる。

### 外部投稿の承認境界

- `check_runtime_health.py`、`migrate_runtime_state.py`、`sync_runtime_credentials.py`、`mirror_to_drive.py` はSNS投稿を行わない
- `auto_post: false` では、対象itemのTelegram **✅承認して投稿** が、設定済み媒体への初回投稿と同じitem内の設定済み自動retryに対する通常の投稿承認になる。callback失敗や古い `approved` 状態を、新しい承認として扱わない
- `retry_failed_posts.py --execute`、手動の再承認・再投稿、`auto_post: true` への変更、初回の実投稿は、実行直前にユーザーの明示承認が必要
- 投稿済みSNSの削除・公開状態変更・アカウント設定変更も、実行直前の明示承認なしに行わない

### 動画被り・二重投稿防止

2026-07-01 に、Claude CLI未ログイン時のフォールバック台本が過去動画と同じ内容を再生成したため、動画被り防止を強化した。

- 台本生成後、直近50本のタイトルと一致する場合は不合格にする
- 字幕・読み上げ文・読み仮名を正規化したキュー署名が直近動画と一致する場合は不合格にする
- フォールバック台本も同じ重複検査に通し、被る場合はqueue登録しない
- 重複検知はDrive outputsではなくruntimeローカル `~/shorts-factory/work/` を見る（Driveロック回避）
- Claude CLIの復旧確認は `claude auth status` と非対話実行 `claude -p` の両方で見る

投稿側は、外部送信の直前に `~/shorts-factory/posting_ledger/` へ `attempting` をatomic保存し、成功後に媒体別URLを `posted` として確定する。worker停止後に `attempting` が残る場合や送信結果が曖昧な場合は `reconcile_required` として盲目的な再投稿を止める。ledgerへ成功URLがある媒体は外部投稿せず、queueへURLだけ復元する。Telegram callback失敗時は承認状態を変更せず、古い `approved` item や一部媒体投稿済みitemはworker側でも再投稿を止める。

重複が見つかった場合は、後続queueを `skipped` にし、`review.reason=duplicate_guard` を残してから別topic/別切り口で再生成する。

### SNS別CTA・説明文

投稿時は `src/platform_copy.py` が媒体別の本文を作る。

- X: 短文内に「最初の1業務」軸のCTAを入れ、プロフィール導線へ誘導
- Instagram: 保存訴求とプロフィールの無料AI導入診断へ誘導
- TikTok: 短い説明とプロフィールの無料診断へ誘導
- YouTube Shorts: 説明欄に `utm_source=youtube` 付きLP URLを直接記載

新規キューには `platform_copy` として媒体別本文を保存する。旧キューに `platform_copy` が無い場合も、投稿時に同じルールで自動生成される。

### AI専門家向けコンテンツ拡張

2026-07-01 以降、動画テーマはChatGPT単体の小技だけでなく、AIツール比較・AI導入・業務自動化・社内定着・品質チェックへ広げる。

- `topics.json` は `domain` / `business_function` / `primary_tools` / `expertise_angle` / `platform_angles` を持つ構造化topicを扱える
- `topics.auto_replenish` が有効な場合、生成前に対象難易度の使用可能ネタを確認し、不足時は内蔵候補から自動補充する。補充候補は ChatGPT / Claude / Gemini / NotebookLM / Canva / Gamma / Make / Zapier などを含む
- 自動補充でも、既存backlog・used・直近queueと類似するtopicは追加しない
- `script_prompt.md` は「AIツール・AI導入・業務自動化」向けに調整済み
- `--target-platform x|instagram|tiktok|youtube` で、台本の見せ方をSNS別に寄せられる
- キューには `content_strategy` と `platform_angles` を保存する
- 投稿文は媒体別の `platform_angles` があれば本文冒頭に反映する
- 英語ツール名・サービス名・英字略語は動画テロップでは英字表記、読み上げ用 `tts_text` / `reading_kana` ではカタカナ読みに分離する

通常運用では `content.platform_variant_videos: true` により、1つのsource topicから有効媒体ごとに別台本・別動画を生成する。

- X / Instagram / TikTok / YouTube それぞれ `target_platform` を変えて台本生成する
- 生成後は1媒体1キューになり、各キューの有効投稿先は対象SNSだけになる
- Telegramプレビューには `媒体別動画: x` のように対象SNSが表示される
- 従来どおり共通動画を使いたい場合は `--single-video` または `content.platform_variant_videos: false` を使う

### Atlas Cloud Seedance 2.0 統合（AI動画背景）

週5枠だけ、静止画カード背景の代わりにSeedance AI動画背景を生成し、音声は日本語TTS（VOICEVOX）で差し替える（反応検証目的）。それ以外の枠は従来どおり静止画版。

- **対象枠**: `mon-09` / `wed-14` / `fri-19` / `sat-14` / `sun-09`（`config.yaml` の `seedance.slots`）。判定は「時」単位マッチ — 例えば `mon-09` は月曜09:00〜09:59台に実行されれば発火する（分は見ない）
- **共通動画モード前提**: Seedance版は `content.platform_variant_videos: false`（共通動画1本、媒体別動画生成とは併用しない）。動画内CTAも「続きはプロフィールから」等の媒体非依存表現にする
- **方式**: `bytedance/seedance-2.0-fast` を使い、カット1は text-to-video、カット2以降は前カットの最終フレームを `start_image` にした image-to-video で連鎖生成し人物・服装・部屋を統一する。Seedanceの外国語訛りを避けるため、`seedance.audio_mode: voicevox` ではSeedance音声を使わず、VOICEVOX男性話者（既定: 青山龍星）で日本語音声を合成して差し替える
- **読み分離（漢字の誤読防止）**: VOICEVOX版と同じ「読み上げは読み仮名で保証・テロップは漢字表記」を採用。台本の各cueは `tts_text`（漢字仮名交じり。字幕・CER検証の基準）と `tts_kana`（tts_textの正確なカタカナ読み）を両方持つ。VOICEVOX合成では `tts_text` を基本にし、読みがずれた場合のみ `tts_kana` にフォールバックする。英語ツール名の読みは既存の `jp_text.TERM_READINGS`（ChatGPT→チャットジーピーティー等）で機械的に畳み込む
- **字幕**: VOICEVOX差し替え音声を既存のwhisper.cpp基盤で文字起こしし、台本の `tts_text` と音韻CER突合して正確性を検証する。`native` 音声モード時のみ `seedance.cer_line_max` / `seedance.cer_avg_max` の緩い閾値を使う
- **フォールバック条件**: APIキー未設定・API失敗/タイムアウト・月次予算超過・1本あたり上限超過・CER不合格継続のいずれでも、自動的に従来の静止画カード版へ切り替わり投稿を止めない
- **コスト上限**: `seedance.monthly_budget_usd`（既定$130/月）・`seedance.max_cost_per_video_usd`（既定$10/本）。超過が見込まれる場合は生成前にフォールバックする
- **コストログ**: `~/shorts-factory/logs/seedance_costs.jsonl`（1行1JSON、日時・動画ID・カット数・秒数・金額・成否を記録）。月次累計はこのログから毎回再計算する
- APIキーは `secrets.yaml` の `atlas_cloud.api_key`（未設定なら常に静止画版）

## 設定変更

- 話者変更: `config.yaml` の `speaker_id`（一覧: `$PY -c "from src import tts_voicevox as t; print(t.speaker_names())"`）
- 投稿先の追加: `queue.platforms` に `youtube` / `instagram` / `tiktok` を追加
- 失敗時の自動再投稿: `queue.retry_failed_posts` / `queue.retry_max_attempts` / `queue.retry_delay_sec`
- CTA先LP: `cta.lp_url` / `cta.campaign`
- 投稿頻度・難易度: `content.scheduled_slots` を変更（標準は 9時=初級、14時/19時=中級）
- AI画像化: `secrets.yaml` に `openai_api_key` か `gemini_api_key` → `images.provider: openai|gemini`
- 台本をOpenAIに: `openai_api_key` 設定 + `llm.provider: openai`

## 障害対応

確認順は固定する。

1. `cd ~/shorts-factory/app && ~/shorts-factory/.venv/bin/python scripts/check_runtime_health.py --json`
2. `~/Library/Logs/shorts-generate.log` / `shorts-approval.log` と、必要なら `shorts-drive-mirror.log`
3. runtime正本の `state/queue/`、`state/topics.json`、`outputs/`、`work/`、`posting_ledger/`
4. `~/shorts-factory/drive_mirror/status.json` の `ok` / `error` / `next_attempt_at`
5. Driveミラーは最後に、コピーの反映遅延や欠損だけを確認する。Drive側をruntime状態の判定や修復に使わない

| 症状 | 対応 |
|---|---|
| Telegramに何も届かない | `tail ~/Library/Logs/shorts-generate.log` / `shorts-approval.log` |
| 品質blocked が続く | `quality_report.json` の `accuracy.lines` を確認。固有名詞なら `src/jp_text.py` の TERM_READINGS に読みを追加 |
| YouTube失敗+スクショ | `~/shorts-factory/logs/yt_fail_*.png` を確認（UI変更ならセレクタ修正） |
| X投稿403 | API無料枠の動画上限。queueは blocked になるので翌日に承認し直す |
| VOICEVOX起動失敗 | `~/shorts-factory/logs/voicevox_engine.log` |
| `runtime migration is incomplete` | 管理された初回移行かを確認して `migrate_runtime_state.py` を実行。既存runtimeを旧Drive状態で上書きする `--force` は安易に使わない |
| `local SNS credentials missing or empty` / mode不正 | `sync_runtime_credentials.py` で明示同期し、再度health checkする。認証値は画面やログへ出さない |
| Driveミラーが失敗・backoff | ローカルhealthとqueue/outputsが正常なら生成・承認・投稿とは切り分ける。`status.json` と `shorts-drive-mirror.log` を確認し、backoff後に `mirror_to_drive.py` を再実行 |
| Drive側のqueue/topicsがruntimeと違う | 正常な非同期遅延として扱い、Driveを手編集・importしない。ローカル正本を確認後にミラーする |
| 一部媒体だけ投稿失敗 | 標準で失敗媒体だけ最大2回自動再投稿。それでも残る場合は `cd ~/shorts-factory/app && ~/shorts-factory/.venv/bin/python scripts/retry_failed_posts.py --all` で対象確認。`--execute` は直前の明示承認後だけ実行 |
| 同じ動画が連続生成される | `script.json` の `title` / `cues` と `~/shorts-factory/work/` の直近履歴を比較。Claude CLIは `claude -p` まで確認し、重複queueは `skipped` にして別topicで再生成 |
| 英語ツール名・英字略語がカタカナで表示される | `src/script_gen.py` の表示正規化辞書と `src/jp_text.py` の読み辞書を追加。旧queueは `skipped`、Telegramボタンを外して再生成し、`subtitles.ass` と動画フレームで焼き込みを確認 |
| 旧queueに `consume_deferred_error` が残る | health checkで件数を確認し、runtime `state/topics.json` とqueueだけを調査する。Drive編集やapproval bot再起動を先に行わず、移行・reconcileの結果を確認する |

## クレジット・コンプライアンス

- 動画内下部とSNS説明文に `VOICEVOX:ずんだもん／音声・映像はAIで自動生成` を自動挿入（VOICEVOX利用規約のクレジット表記）
- フォントは Noto Sans JP（SIL OFL）
- BGMは初期オフ（権利クリアな音源を `assets/bgm/` に置いた場合のみ使用）
