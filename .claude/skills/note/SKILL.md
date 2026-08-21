---
name: note
description: note販売を、Planner・Architect・Writer・Promoter・Analyst・Director・媒体別Publisherの分業で、企画、構成、章単位執筆、X告知案、note公開、X本投稿と1件目リプ、実績分析、改善まで承認制で進める。ユーザーが「noteを仕組み化」「note AIチーム」「note自動販売」「企画から分析まで」「/note」「$note」と依頼したときに使う。既存5アカウント、履歴、ペルソナ、画像ルールを再利用し、公開・投稿は媒体別の個別承認後にworkerが自動実行する。
---

# note販売AIチーム

## 正本と入力

最初に次を読む。

1. `.company/secretary/HANDOFF.md` と当日の最新TODO
2. `.company/projects/note販売AIチーム/config/team.json`
3. `.company/projects/note販売AIチーム/config/constitution.md`
4. `.company/outputs/note-articles/accounts.json` と `history.json`
5. 対象アカウントの `persona_file`
6. `.company/projects/note販売AIチーム/data/style-candidates.json`
7. `.company/projects/note販売AIチーム/data/style-corpus.json`
8. 有料フローでは `data/fact-pack-template.md`
9. 対象runの `state.json`（既存runを再開するとき）

Claude Codeから渡された引数は `$ARGUMENTS` として扱う。置換されない環境では、ユーザーの自然言語を同じ意味の入力として扱う。

## コマンドの意味

- 引数なし / `status`: run一覧と次の安全な操作を表示する
- `new <テーマ>` / `start <テーマ>`: 承認済みstyle corpusを検証し、新規runを作って企画をレビュー待ちまで進める。未承認・改変時はrun作成自体を停止する
- `resume <run-id>` / `continue <run-id>`: 現在工程を読み、次の承認待ちまで進める
- `promote <run-id>`: 承認済み本文からX案3種をJSONで作り、承認画面で1案選択する
- `publish-note <run-id>`: `note_publish` 事前確認まで進め、個別承認後にworkerが既存下書きを公開・読み戻す
- `post-x <run-id>`: `x_publish` 事前確認まで進め、個別承認後にworkerが本投稿と1件目リプを投稿・API読み戻す
- `analyze <YYYY-MM>`: 実値CSVを集計し、Analystに解釈させる
- `approve` / `revise` / `reject`: ローカル承認画面で人間が判断する。AIやCLIからの承認代行は受け付けない

状態変更には必ず `python3 tools/note-sales-team/note_team.py` を使う。`state.json` を直接編集しない。

## 単一ライター

同じrunを更新するPCは常に1台だけにする。ファイルロックは同一ホスト内の競合だけを防ぎ、Google Driveで共有されたMac・Windows間の分散ロックにはならない。PCを替える場合は、元PCの承認画面と関連エージェントを終了し、Drive同期完了後に移行先で `status RUN_ID` の `revision` と末尾 `audit_log` が元PCの最終状態と一致することを確認してから再開する。不一致や競合コピーがある場合は更新しない。

## 新規run

1. `style-candidates.json` の固定note 3本・X 20件と制約を127.0.0.1の承認画面でオーナーが確認し、`style-corpus.json` を承認済みにする。noteの売上は不明、Xの反応は小規模であり、「売れた」「高反応」の認定ではない。AIやCLIはこの承認を代行しない。
2. 対象アカウント・テーマを既存設定から解決する。未指定は `team.json` の既定値を使う。
3. `free-standard` と `paid-longform` を混同しない。有料長文はfact packなしで企画3案まで作れるが、採用企画の承認前にオーナー承認済みfact packを固定する。
4. 次を実行する。

```bash
python3 tools/note-sales-team/note_team.py create \
  --account ACCOUNT_ID --theme THEME_ID --slug ASCII_SLUG --profile PROFILE
```

5. Plannerを使い、`proposal_id: plan-01` 〜 `plan-03` をその順に1回ずつ含む企画3案を `runs/<run-id>/plan.md` に保存する。
6. Directorを独立実行し、成果物SHA-256に紐づくQA JSONを作る。PASS、FAIL、fatalを問わず次の `submit --qa-artifact` を1回実行し、判定を状態へ記録する。
7. 次の形でsubmitする。すべての非外部工程で `--qa-artifact` は必須。FAILは非0終了してreviewへ進まず修正待ちとなる。fatalはrunを即時停止する。QAをsubmitせず独自に差し戻してはならない。

```bash
python3 tools/note-sales-team/note_team.py submit RUN_ID plan plan.md \
  --actor note-planner --qa-artifact qa/plan-final.json
```

8. 承認画面で `plan-01`〜`plan-03` から1案を選び、その後に承認・修正・却下する。企画選択も承認も推測しない。
9. `paid-longform` ではfact pack先頭を `owner_approved: true` にし、タイムゾーン付き `approved_at` を記入してから固定する。固定だけでは承認済みにならない。内容とSHA-256を承認画面でオーナーが確認する。

```bash
python3 tools/note-sales-team/note_team.py attach-fact-pack RUN_ID PATH_TO_FACT_PACK
```

## 工程フロー

工程契約は `references/phase-contracts.md`、役割指示は `references/roles/` を読む。

1. `plan`: Plannerの3案 → Director → 人間が1案選択 → 人間承認
2. `outline`: Architect → Director → 人間承認
3. `draft`: outlineの章IDを `set-units` で登録 → Writerが章ごとに作成 → Director → 章ごとに人間承認 → 結合原稿をDirector → 最終承認
4. `promotion`: PromoterがX案3種とリンク用リプ案を機械可読JSONで作成 → Director → 人間が1案選択・承認。Promoterは投稿しない
5. `note_draft`: 書き込み前のnote IDと、保存を生まない空の `https://note.com/notes/new` を `preflight` → ローカル画面でオーナー許可 → ブラウザ書き込み直前に `claim-external` で許可を1回限り消費 → 5分以内に既存 `note-article-publisher` で新規下書き保存。投入元は `state.json` のdraft工程が指す承認済み `.snapshots/` 原稿に限る。このclaimでは公開しない
6. `note_publish`: 元draft ID、note ID、原稿・下書き結果SHA、本文・公開設定を読み取りだけで `preflight --stage note_publish` → note公開専用のオーナー許可 → claim → 既存下書きのみを公開 → 公開URL・本文・設定を読み戻し。公開URLの記事IDと元draft IDが一致しなければ受理しない。失敗・結果不明では公開ボタンを再クリックしない
7. `x_publish`: X APIの本人user ID/username、選択案、確定note URLを `preflight --stage x_publish` で固定 → X投稿専用のオーナー許可 → claim → 本投稿を1回POST・IDをcomponent台帳へ保存 → 1件目リプをPOST → URL entityを展開した本文と両方のauthor/返信先をAPIで読み戻し。リプ失敗時に本投稿を再POSTせず、本投稿済みのcomponent台帳もリセットしない
8. `analysis`: `data/note_metrics.csv` と `data/x_metrics.csv` の実値を決定論的に集計 → Analyst → Director → 人間承認

各工程はDirector 85点以上になってから人間レビューへ出す。不合格QAも必ずsubmitして試行回数へ記録し、修正は工程ごと最大5回。致命的違反は点数に関係なく停止する。

5回に達すると `owner_escalation` で自動停止する。承認画面でオーナーが「run却下・停止」または「追加1ループを明示許可」を選ぶまで再開しない。

Director QA JSONの必須形式は `references/phase-contracts.md` を正とする。システムはsubmit時のバイトを `.snapshots/` へ固定し、SHA-256が変わった成果物を承認しない。

## サブエージェント

Claude Codeでは `.claude/agents/note-team/` の `note-planner`、`note-architect`、`note-writer`、`note-promoter`、`note-analyst`、`note-director` を前景で順番に使う。Codexでは同名の役割ごとに独立サブエージェントを起動し、`references/roles/<role>.md` を渡す。

PlannerとAnalystを同時に走らせない。Plannerは直近実績を入力にし、Analystは公開後実績を次回Plannerへ渡すため、同一runでは順序依存である。

## 承認画面

次を実行し、表示された127.0.0.1のURLを開く。

```bash
python3 tools/note-sales-team/note_team.py serve
```

初回URLのトークンは1回だけCookieへ交換され、承認画面は127.0.0.1のみで動く。「文体コーパス承認」「承認」「修正」「却下」「企画選択」「X案選択」「fact pack承認」はローカル状態だけを変更する。文体コーパス承認は表示中の候補packとregistryのSHA-256に固定し、改変・古い画面・別内容の上書きを拒否する。`note_draft`、`note_publish`、`x_publish` の許可は互いに独立した10分間・1回限り許可で、claim後の実行窓は5分。一つの許可を他媒体や次工程へ流用しない。

## 分析

指標定義は `references/metrics-schema.md` を読む。CSVにない値は `N/A` とし、推測や逆算で補わない。

```bash
python3 tools/note-sales-team/note_team.py analyze --month YYYY-MM
```

## 外部操作の安全境界

- note下書き、note公開、X投稿はそれぞれ独立した承認として扱い、承認後だけ専用workerが実行する
- すべての外部操作は `claim-external` 後に行う。失敗やタイムアウト後は `reconciliation_required` で同じ操作の自動再試行を禁止し、同じclaim IDの外部結果を照合する。既存結果は同じclaimで記録し、note一覧またはX APIで不存在をオーナーがローカル画面確認した場合だけ事前確認と許可を取り直す
- X本投稿成功後にリプが失敗したときは本投稿を再POSTしない
- LINE送信、予約投稿、定期公開はこのスキルで実行しない
- noteアカウントが一致しない、画面確認できない、ログアウト中のいずれかならnote側へ一切書き込まない
- パスワード、Cookie、APIキー、トークンをファイルに保存しない
- 画像はChatGPT Pro Webの `gpt-image-2` だけを使い、APIやローカル生成へ切り替えない
