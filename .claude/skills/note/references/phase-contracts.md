# 工程契約

## 全工程共通のDirector QA

`note_draft` の画面確認記録以外は、成果物と別にDirector QA JSONを作り、`submit --qa-artifact` で渡す。

```json
{
  "stage": "draft",
  "unit": "chapter-01",
  "checked_artifact_sha256": "64桁のSHA-256",
  "score": 90,
  "verdict": "PASS",
  "fatal_violations": [],
  "checked_at": "2026-07-19T10:00:00+09:00",
  "reviewer": "note-director"
}
```

- `unit` は工程全体なら `null`、章単位なら章ID
- 人間レビューへ進める条件はscore 85以上、`verdict=PASS`、致命的違反0件
- SHA-256とタイムゾーン付き時刻をツールが検証する
- submitバイトは `.snapshots/` に固定され、後から元ファイルを変えても承認対象は変わらない
- PASS、FAIL、fatalの全QA JSONを `submit --qa-artifact` へ渡す。FAILは非0終了して成果物をreviewへ進めず、品質ゲート失敗として工程の試行に数える。5回でオーナー判断へ停止し、fatalは初回でもrunを停止する

## plan

入力: 対象アカウント、ペルソナ、直近30日履歴、過去実績、公開情報、owner fact pack。

出力: `proposal_id: plan-01`、`plan-02`、`plan-03` の順に企画3案。各案にテーマ、需要根拠とURL・確認日、想定価格、購入層、差別化、本人が語れる根拠、リスクを付ける。一般論だけの案を除外する。

承認: ローカル承認画面で3案から1案を選択してから、工程全体を承認する。`paid-longform` はこの承認前にowner fact packをrunへ固定し、内容とSHA-256をローカル承認画面でオーナーが承認する。以後の有料工程は毎回そのSHA-256を再検証する。

## outline

入力: `state.json.selected_plan_id` で選ばれた承認済み企画1案だけ。

出力: 章ID、章タイトル、小見出し、章の役割、必要な事実資料、目標文字数。`free-standard` はアカウント文字数、`paid-longform` は1.5〜2万字・8〜10章を守る。実例・失敗・実行手順を配置する。

`set-units` は `free-standard` 4〜7章、`paid-longform` 8〜10章を機械検証する。

## draft

入力: 承認済みoutline、対象ペルソナ、候補packとSHA-256が一致する `status=approved` のstyle corpus、owner fact pack。style corpusが未承認、note 3本でない、X 20本でない、または元資料が改変された場合は執筆せず停止する。本人の文体の「完全再現」は承認後も保証しない。

出力: 章別Markdown。体験・数字ごとに根拠を追跡できるようにする。根拠がない箇所は書かず `[要確認]` とする。章末に次章への自然な接続を置く。

章ごとの人間承認後に結合原稿を作り、Directorの最終レビューへ出す。

結合原稿submit時にツールも文字数下限・上限を検証する。字数は「MarkdownのリンクURL、HTMLタグ、制御記号、空白を除いた可視テキストのUnicode文字数」とし、画像altとリンク表示文字は数える。

## promotion

入力: 承認済み最終原稿。

出力: 次のJSON。`promotion_id` は `x-01` / `x-02` / `x-03` を順番どおりに1回ずつ使う。本投稿にはURLを入れず、`reply_text_template` に `[NOTE_URL]` を1回だけ入れる。各文面はXのURL=23文字・日本語等=重み2の文字数計算で280以内にする。Promoter自身は投稿しない。

```json
{
  "variants": [
    {
      "promotion_id": "x-01",
      "intent": "共感から具体策へつなぐ",
      "primary_text": "X本投稿本文",
      "reply_text_template": "詳細はこちら [NOTE_URL]"
    }
  ]
}
```

承認画面でオーナーが1案選び、選択IDとpromotion承認版SHA-256を固定する。

## note_draft

入力: 承認済み原稿、画像、投稿先設定、書き込み前事前確認、外部操作の個別許可。

事前確認JSON:

```json
{
  "account_id": "you-ai-dx",
  "expected_note_id": "you_ai_dx",
  "observed_note_id": "you_ai_dx",
  "editor_ready": true,
  "operation": "create_new_draft",
  "editor_url": "https://note.com/notes/new",
  "initial_content_empty": true,
  "checked_at": "2026-07-19T10:00:00+09:00"
}
```

`preflight` は、承認前にnoteへ保存しない空の新規投稿画面とアカウントの読み取り確認だけに限る。固定後、オーナーが承認画面で許可する。許可は原稿SHA-256と事前確認SHA-256に紐づく10分間・1回限り。ブラウザ書き込み直前に `claim-external` し、保存はclaimから5分以内に完了する。

`external-failure` 後は `reconciliation_required` で自動再投入を止め、claim IDと固定SHAを保持する。noteの下書き一覧で既存結果が見つかったら同じclaim IDで結果JSONをsubmitする。見つからない場合だけ、ローカル承認画面で「下書き不存在」の確認内容を入力し、事前確認とオーナー許可をやり直す。

初期版の結果JSONはブラウザ担当の自己証明で、状態ツールはエディタDOM本文を独立読み戻ししない。人間が `note_draft` を承認する前に `draft_url` を開き、タイトル、本文冒頭、本文末尾、途中欠落、画像を承認済み `.snapshots/` 原稿と目視照合する。無人実行はDOM正規化digest・文字数・冒頭末尾sentinel・画面証跡が実装されるまで行わない。

出力: 下書きURLと次の画面確認JSON。このclaimでは公開画面の投稿ボタンを押さず、`note_draft` 承認後の別工程 `note_publish` へ渡す。

```json
{
  "account_id": "you-ai-dx",
  "expected_note_id": "you_ai_dx",
  "observed_note_id": "you_ai_dx",
  "operation": "create_new_draft",
  "initial_content_empty_before_write": true,
  "editor_draft_id": "n...",
  "draft_url": "https://editor.note.com/notes/n.../edit/",
  "saved_indicator": true,
  "published": false,
  "draft_saved_at": "2026-07-19T10:04:00+09:00",
  "checked_at": "2026-07-19T10:05:00+09:00",
  "claim_id": "state.jsonの現行claim_id",
  "manuscript_sha256": "state.jsonの承認済みdraft SHA-256",
  "preflight_sha256": "state.jsonの事前確認SHA-256",
  "image_status": {
    "mode": "image-free",
    "heading_image_verified": false,
    "inline_images_expected": 0,
    "inline_images_verified": 0,
    "pending": []
  }
}
```

## note_publish

入力: 承認済み `note_draft` 結果、承認済み原稿、公開設定、読み取り専用事前確認、`note_publish` 専用の個別許可。

事前確認JSONは、予定・表示note ID、元editor draft ID/URL、下書き結果SHA-256、原稿SHA-256、本文読み戻し、公開設定確認、公開ボタン準備、未公開、確認時刻を持つ。

```json
{
  "account_id": "you-ai-dx",
  "expected_note_id": "you_ai_dx",
  "observed_note_id": "you_ai_dx",
  "operation": "publish_existing_draft",
  "editor_ready": true,
  "editor_draft_id": "n...",
  "draft_url": "https://editor.note.com/notes/n.../edit/",
  "draft_record_sha256": "...",
  "manuscript_sha256": "...",
  "content_readback_verified": true,
  "publish_settings_verified": true,
  "publish_button_ready": true,
  "published": false,
  "checked_at": "2026-07-19T10:00:00+09:00"
}
```

`preflight RUN_ID ... --stage note_publish` 後、ローカル承認画面で個別許可する。workerは `claim-external RUN_ID note_publish` 直後だけ、その下書きの「公開に進む」から「投稿する」を操作する。公開後はボタン応答でなく、公開ページのnote ID、URL、本文、設定、公開時刻を読み戻す。公開URLの記事IDは元の `editor_draft_id` と完全一致させ、同じアカウントの別記事URLを結果として受け付けない。通信断で結果不明なら再クリックせず `reconciliation_required` で公開記事一覧と下書き一覧を照合する。

結果JSONには上記binding、`public_url`、`published: true`、`published_at`、`checked_at`、`claim_id`、`preflight_sha256`、公開ページの本文・設定読み戻し結果を含める。

## x_publish

入力: 承認済み `note_publish` 結果、選択済みpromotion案、X APIの読み取り本人確認、`x_publish` 専用の個別許可。

事前確認JSONには、予定・観測X user ID/username、`selected_promotion_id`、確定本文、公開note URLを展開したリプ本文、両文面SHA-256、promotion/note公開結果SHA-256、重み付文字数検証、確認時刻を含める。

workerはclaim後に本投稿を1回だけPOSTし、ID/URLを `components.main` へ原子的に固定してから、`in_reply_to_tweet_id` に本投稿IDを指定して1件目リプをPOSTする。両tweetをAPIで読み戻し、URL entityの `expanded_url` を復元した本文、author ID、返信先を検証した結果だけをsubmitする。

本投稿成功後にリプが失敗・結果不明になった場合、本投稿を再POSTしない。`components.main` が `posted` なら「結果不存在」で台帳をリセットする操作も禁止する。`components.reply` も `posted` なら同じclaimの読み戻し結果をsubmitできる。リプIDが台帳に固定されていなければ、後付けで別tweetを帰属せずrunを停止する。

即時確認でも後日照合でも、`draft_saved_at` はclaim後かつ5分期限内、`checked_at` は現在の画面確認時刻とする。後日照合で古いpreflightを再許可に流用したり、新規下書きを作り直したりしない。

画像ありは `mode=verified`、`heading_image_verified=true`、本文画像のexpected=verified、pending空配列を必須とする。

## analysis

入力: `note_metrics.csv` と `x_metrics.csv` の実値集計、承認済み原稿、企画メモ。集計には生成日時、フィルタ後行数、入力CSVのSHA-256を含める。

出力: 先頭に `metrics_month`、`note_csv_sha256`、`x_csv_sha256`、`metrics_snapshot_sha256` の4行。最後の値は生成時刻を除いた決定論的集計JSONのSHA-256。続けて今月の総括、続けること、やめる・変えること、次テーマ方向性を各ひとつ出す。数値は機械集計レポートだけを正本とし、Analyst解釈本文に数字を再記載しない。submit時に4値と現行CSVを機械照合する。
