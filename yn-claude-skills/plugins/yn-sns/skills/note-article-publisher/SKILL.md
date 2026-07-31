---
name: note-article-publisher
description: 複数テーマ・複数noteアカウントで毎日投稿するための記事作成からnote即時投稿までを行うスキル。AI・お金・キャリア・スピリチュアル・恋愛の5アカウントを標準ペルソナとして持ち、週次バッチで7日分×5アカウント=35記事を下書きまで一括生成できる。accounts.jsonでテーマごとの投稿先アカウントとブラウザプロファイルを管理し、history.jsonで過去記事履歴を確認して内容の重複と誤投稿を防ぎ、トップ画像・本文中画像つきのnote投稿用Markdownを生成する。ユーザー承認後はブラウザでnoteに下書き投入、見出し画像設定、公開設定確認、即時投稿完了確認、履歴更新まで行う。予約投稿はユーザーが明示した場合のみ扱う。ユーザーが「note記事を書いて/投稿して」「今週分のnote記事を一括生成」「noteの週次バッチ」などnoteへの記事作成・投稿を依頼したときに使う。
---

# note Article Publisher

## 目的

note向けの記事を、複数テーマ・複数アカウントで継続投稿する。毎回、投稿先アカウント、過去記事履歴、テーマの重複、画像構図の重複を確認し、誤投稿を防ぎながら投稿用素材一式を作る。

企画・構成・章別承認・X告知案・販売分析までを一つのチームで回す依頼は、上位の `note` スキルを使う。このスキルは、その下位工程である記事素材作成、note下書き投入、別承認後のnote公開を担当する。

### 上位 `note` runの場合の優先ルール

`.company/projects/note販売AIチーム/runs/<run-id>/state.json` から呼び出された場合、このスキルの単発・週次承認例外ではなく、上位 `note` スキルの per-run ゲートを必ず優先する。

- 投入原稿はstateのdraft工程が指す承認済み `.snapshots/` ファイルだけ
- `note_draft` 工程の `preflight` は正しいnote IDと、保存を生まない空の `https://note.com/notes/new` の読み取り確認だけとする。ローカル承認画面のオーナー許可なしに本文入力や保存をしない
- ブラウザ書き込み直前に `claim-external RUN_ID note_draft` を実行し、10分間・1回限りの許可を消費する。新規下書きの保存はclaim後5分以内に行い、Step 6の保存確認で一度停止する
- 下書き保存後はclaim ID、原稿SHA-256、事前確認SHA-256、`operation=create_new_draft`、editor draft ID、`draft_saved_at`、現在の `checked_at`、画像反映を含む確認JSONを残す
- stateが `note_publish` へ進んだ後に、承認済み `note_draft` 結果が指す同一下書きURL、アカウント、タイトル、原稿SHA-256、公開設定を照合し、`preflight --stage note_publish` を登録する
- `note_publish` の別承認後に限り、公開操作の直前に `claim-external RUN_ID note_publish` を実行してStep 7〜11へ進む。`note_draft` の承認やclaimを公開許可に流用しない
- 公開後は同じclaim ID、公開URL、公開時刻、タイトル、note ID、公開画面の読み戻し結果を含む確認JSONを登録する。公開URLの記事IDは元のeditor draft IDと完全一致させる
- どちらの工程も失敗・タイムアウト時は `external-failure` を記録し、`reconciliation_required` で新規操作を停止する。下書き一覧または公開一覧を照合し、結果不明のまま保存・公開ボタンを再操作しない
- 初回外部パイロットでは下書きURLを開いたまま止め、オーナーがタイトル・本文冒頭・本文末尾・途中欠落・画像を承認済みスナップショットと目視照合し、その後に `note_publish` を別承認する。確認JSONだけを実DOMの独立証拠として扱わない

## 標準5アカウント

このスキルは以下の5アカウント運用を標準サポートする。各アカウントのペルソナ・文体・NG・文字数・構成は `references/personas/<account_id>.md` に定義済み。記事生成前に必ず対象アカウントのペルソナファイルを読み込んでから書き始める。

| account_id | display_name | テーマ領域 | 文字数 |
|------------|--------------|-----------|--------|
| ai | AI活用ノート | 現場のAI活用 | 3500-5000 |
| money | お金の整え方 | 派手じゃない着実な資産形成 | 2500-4000 |
| career | キャリアの選びなおし | 会社員の出口戦略 | 3000-4500 |
| spiritual | 整える日々 | 日常で使える整え方 | 1800-3000 |
| love | 続く関係の手前で | 続く関係の小さな技術 | 2000-3500 |

初期セットアップは `templates/accounts.json.example` を `.company/outputs/note-articles/accounts.json` にコピーし、各アカウントの `note_url` を埋める。

## 運用モード

このスキルは2つのモードを持つ。

1. **単発モード**: 1記事だけ生成・即時投稿する。デフォルト。下記の「ワークフロー」を使う。
2. **週次バッチモード**: 5アカウント × 7日 = 35記事を下書きまで一括生成する。詳細は `references/weekly-batch.md` を読み込んでから実行する。Task Scheduler 自動起動の手順は `references/task-scheduler-setup.md` を参照。

ユーザーが「今週分」「週次バッチ」「7日分まとめて」と言ったら週次バッチモード、それ以外は単発モード。

## 管理ファイル

- `.company/outputs/note-articles/accounts.json` - テーマごとの投稿先アカウント設定
- `.company/outputs/note-articles/history.json` - 投稿履歴
- `.company/outputs/note-articles/topics/<account_id>.md` - 週次バッチで消化するトピックキュー
- `.company/outputs/note-articles/YYYY-MM-DD-{theme_id}-{slug}/` - 単発モードの記事ごとの出力先
- `.company/outputs/note-articles/weekly/YYYY-WNN/` - 週次バッチモードの週単位出力

## 入力

- テーマまたは `theme_id`（必須または提案）
- 投稿先 `account_id`（任意。未指定なら `accounts.json` からテーマに対応するアカウントを選ぶ）
- 想定読者（任意。未指定ならアカウント設定とテーマから提案）
- 投稿日（任意。未指定ならツールで今日の日付を確認）
- 画像点数（任意。デフォルトはトップ画像1枚 + 本文中画像3枚）
- 投稿状態（任意。未指定は `draft`）

## 出力

記事フォルダに以下を作る。

- `note-post-ready.md` - note投稿画面に入れる本文
- `article.md` - タイトル案、抜粋文、制作メモも含む完全版
- `image-placement.md` - トップ画像と差し絵の配置表
- `quality-check.md` - 100点満点の品質チェック
- `images/top-*.png` - note見出し画像
- `images/inside-*.png` - 本文中画像

## 必須ルール

1. 作業前に日付をツールで確認する。
2. `accounts.json` と `history.json` を必ず読む。存在しない場合は最小構成で作成する。
3. テーマに対応する `account_id` を決めてから記事を作る。
4. **`account_id` が決まったら、`accounts.json` の対象アカウントにある `persona_file` を必ず読み込んでから本文に取りかかる。** `persona_file` がない場合だけ `references/personas/<account_id>.md` を使う。ペルソナ未参照のまま本文を書き始めない。
5. 履歴を見て、テーマ・切り口・タイトル構造・見出し・画像構図が被らないようにする。
6. 記事作成前に、今回の記事が過去記事とどう違うかを「差別化メモ」として決める。
7. 画像生成が必要な場合は ChatGPT Pro Web の ChatGPT Images 2.0 / `gpt-image-2` で作成する。OpenAI API、`openai-image-gen` の旧API実行、APIキー、Pillow/ローカル生成画像への代替は禁止。生成できない場合はプロンプトと配置指示を保存し、画像ステータスを `pending_gpt_image2_web` または `blocked_gpt_image2_web` にする。
8. トップ画像は本文内に重複挿入せず、noteの「見出し画像」として指定する。
9. 品質チェックは100点満点で行い、85点未満なら修正する。ペルソナのNG項目に該当する表現が含まれていたら即減点する。
10. 完成後、`history.json` に必ず記録する。
11. noteへの下書き投入、即時投稿、予約投稿、公開操作はユーザーの明示承認なしに実行しない。**ただし週次バッチモードでオーナーが運用承認済みの場合は、下書き保存までは承認なしで進めてよい（公開ボタンは押さない）。**
12. ブラウザ操作後は、note画面上の完了表示を確認してから履歴を更新する。

## accounts.json の考え方

テーマごとに投稿先アカウントを固定する。パスワードやCookieは保存しない。

```json
{
  "accounts": [
    {
      "account_id": "career",
      "display_name": "未設定",
      "note_url": null,
      "theme_ids": ["40s-career"],
      "browser_profile": "note-career",
      "default_tags": ["キャリア", "40代", "働き方"],
      "tone": "落ち着いた実践寄り",
      "status": "setup-required"
    }
  ],
  "themes": [
    {
      "theme_id": "40s-career",
      "theme_name": "40代キャリア再設計",
      "account_id": "career",
      "audience": "40代で働き方や将来に不安がある人",
      "avoid_angles": ["手放すものを決める"],
      "preferred_angles": ["副業実験", "社内で役割を変える", "AI時代に経験を翻訳する"]
    }
  ]
}
```

## ログイン方式

標準は「ブラウザプロファイル方式」とする。

- アカウントごとに専用ブラウザプロファイルを作る
- 例: `note-career`, `note-ai-side-business`, `note-freelance`
- 各プロファイルでは、ユーザーが一度だけ手動ログインする
- スキルや履歴ファイルにパスワード、Cookie、セッション情報を保存しない
- 2段階認証が出た場合はユーザーが手動で対応する

誤投稿防止:

- 投稿前に予定 `account_id` と現在のnote表示名またはURLを照合する
- 一致しない場合は投稿せず停止する
- 自動化時も、最初は「下書き保存」までを標準にする
- 公開はユーザー承認後に行う

## 重複防止

履歴の以下を確認する。

- `account_id`
- `theme_id`
- `title`
- `theme`
- `audience`
- `angle`
- `headings`
- `keywords`
- `image_themes`
- `status`

避けること:

- 同じアカウントで直近30日以内に同じテーマ・同じ悩みを扱う
- 別アカウントでも、同じ切り口の記事を近い日に出す
- 同じタイトル型を連続させる
- 同じ導入パターンを続ける
- 同じチェックリスト項目を使い回す
- 同じ画像構図を連続させる

似たテーマを扱う場合は、履歴にない切り口を選ぶ。

例:

- 済: 40代キャリア再設計 / 手放すものを決める
- 次: 40代キャリア再設計 / 副業を始める前の小さな実験
- 次々回: 40代キャリア再設計 / 社内で役割を変える交渉術
- 別切り口: 40代キャリア再設計 / AI時代に経験を翻訳する

## ワークフロー

### Step 1: アカウント・履歴確認

1. 今日の日付を確認する。
2. `accounts.json` を読む。
3. `history.json` を読む。
4. 今回の `theme_id` と `account_id` を決める。
5. 直近30日と同テーマの記事を確認する。
6. 差別化メモを作る。

### Step 2: 要件定義

必要に応じて以下を提示し、ユーザー承認を得る。

- 投稿先アカウント
- テーマ
- 想定読者
- 今回の切り口
- 過去記事との差別化
- 画像点数
- 完了条件
- 品質基準

ユーザーが明確に進行を承認している場合は、合理的な前提で進める。

### Step 3: 記事構成

以下を作る。

- タイトル案5本
- 採用タイトル1本
- 見出し構成
- 導入の刺し方
- 保存されやすい実用パート
- ハッシュタグ

文字数は原則2,500-3,500字。

### Step 4: 本文作成

以下を満たす本文を書く。

- 冒頭3行で読者が自分ごと化できる
- 共感だけで終わらず、具体的な行動に落とす
- アカウントのトーンに合っている
- 露骨な営業臭を出さない
- 最後に保存用チェックリストを入れる

### Step 5: 画像生成

トップ画像1枚、本文中画像2-3枚を作る。画像は記事フォルダ内の `images/` に保存する。

トップ画像:

- note見出し画像として使う
- 横長16:9
- 記事の主題が一目で伝わる
- 文字を入れない

本文中画像:

- 見出しの流れに合わせる
- 画像ごとに役割を分ける
- 同じ構図を繰り返さない
- 文字・ロゴ・読める看板を避ける

### Step 6: 投稿用ファイル作成

`note-post-ready.md` には以下を入れる。

- 投稿先アカウント
- タイトル
- トップ画像の指定
- note投稿画面へ貼る本文
- 本文中画像のMarkdown
- ハッシュタグ

`image-placement.md` には以下を入れる。

- 見出し画像のパス
- 各差し絵のパス
- 各差し絵の挿入位置
- 各画像の役割

### Step 7: 品質チェック

`quality-check.md` に100点満点で記録する。85点未満なら修正する。

評価項目:

- 投稿先アカウント適合
- 過去記事との差別化
- テーマ適合
- 冒頭の引き
- noteらしい読み心地
- 具体性
- 保存したくなる要素
- 画像の自然さ
- 画像配置
- 投稿用ファイルの使いやすさ
- 誤投稿防止情報の明確さ

### Step 8: 履歴更新

完成後、`history.json` に以下を追記する。

```json
{
  "date": "YYYY-MM-DD",
  "account_id": "career",
  "theme_id": "40s-career",
  "title": "記事タイトル",
  "theme": "テーマ",
  "audience": "想定読者",
  "angle": "切り口",
  "headings": ["見出し1", "見出し2"],
  "keywords": ["キーワード1", "キーワード2"],
  "image_themes": ["トップ画像", "本文中画像1"],
  "output_dir": ".company/outputs/note-articles/YYYY-MM-DD-theme-slug",
  "status": "draft",
  "draft_url": null,
  "posted_url": null
}
```

## note即時投稿フロー

標準の投稿方式は即時投稿とする。ユーザーが「noteに投稿して」「公開して」などと明示し、投稿先が決まっている場合に実行する。投稿は第三者サービスへの送信なので、開始前に必ずユーザー承認を得る。承認済みでない場合は、下書き投入や `投稿する` ボタン押下の直前で止める。

### 事前確認

1. ツールで現在日時と曜日を確認する。
2. `accounts.json` と `history.json` を読み、対象 `account_id` と `theme_id` を確認する。
3. 投稿先note URLと現在ログイン中アカウントを照合する。
   - note ID、表示名、またはアカウント設定画面で確認する。
   - 一致しない場合は投稿操作を停止する。
4. 投稿前に `quality-check.md` が85点以上か確認する。

### 投稿素材の準備

1. `note-post-ready.md` からタイトルと本文を使う。
2. note本文へ貼り付ける本文は、必要に応じてMarkdown画像行を除外したプレーン本文を作る。
3. 見出し画像と本文中画像は、ブラウザのファイル選択で扱いやすい一時フォルダへコピーしてよい。
   - 例: `/tmp/note_upload_ai/`
   - Google Drive配下や日本語パスでファイル選択が詰まる場合の回避策として使う。
4. トップ画像はnoteの「見出し画像」としてアップロードする。
5. 本文中画像は、`image-placement.md` の指定位置に挿入する。アップロードが長時間停止する場合は、下書き保存を優先し、未反映の画像を `quality-check.md` に記録する。

### ブラウザ投入手順

> 上位 `note` runでは `note_draft` claimでStep 6まで実行し、一度停止する。Step 7〜11は、stateが `note_publish` で別の事前確認・承認・claimを完了した場合に限り、同一下書きに対して実行する。

1. note新規記事画面を開く。
2. タイトルを貼り付ける。
3. 本文を貼り付ける。
4. 見出し画像をアップロードし、必要なトリミング保存を行う。
5. 本文中画像を指定位置へ挿入する。
6. `下書き保存` を押し、保存済み表示を確認する。
7. `公開に進む` を押す。
8. ハッシュタグ、無料/有料、マガジン、自動翻訳、AI学習対価還元、コメント設定などを確認する。
   - 特にユーザー指定がなければ、記事タイプは無料のままにする。
   - ユーザー指定がなければ、既定の詳細設定は変更しない。
9. 予約投稿の日時設定は開かない。即時投稿では、公開設定画面右上のボタンが `投稿する` であることを確認する。
10. 単発モードはユーザー承認済み、上位runは `note_publish` claim済みの場合のみ `投稿する` を押す。
11. 投稿完了表示または公開後URLを確認する。

### 完了後の履歴更新

即時投稿完了後、`history.json` の対象記事を更新する。

```json
{
  "status": "posted",
  "posted_at": "YYYY-MM-DDTHH:MM:SS+09:00",
  "timezone": "Asia/Tokyo",
  "draft_url": "https://editor.note.com/notes/{note_id}/edit/",
  "posted_url": "https://note.com/{account}/n/{note_id}"
}
```

`quality-check.md` も更新する。

- Posting: PASS
- 即時投稿完了を画面確認済み
- 本文中画像が未反映または未確認なら Images は `PARTIAL PASS` とし、理由を書く

## note予約投稿フロー（一時停止中）

現在の標準運用では予約投稿を使わない。ユーザーが明示的に「予約投稿に戻す」「指定日時で予約して」と依頼した場合のみ、`references/scheduled-posting.md` を読み込んでこのフローを実行する。即時投稿の依頼ではこのファイルを開かない。

## 上位 `note` runの承認後自動公開フロー

上位 `note` runの `note_draft` と `note_publish` は、ブラウザプロファイル方式で自動実行する。

1. `accounts.json` の `browser_profile` で対象プロファイルを開く。
2. note投稿画面を開く。
3. 現在ログイン中の表示名またはURLを確認する。
4. `accounts.json` の予定アカウントと一致するか照合する。
5. 見出し画像をアップロードする。
6. 本文と本文中画像を配置する。
7. 下書き保存する。
8. 下書きURLを取得して `history.json` の `draft_url` に入れる。
9. 標準では予約投稿の日時設定を開かず、即時投稿として進める。
10. `note_publish` の事前確認・別承認・claimがそろった場合のみ `投稿する` を押す。
11. 公開後、`status` を `posted`、`posted_url` を投稿URLに更新する。
12. ユーザーが明示した場合のみ予約投稿を使い、予約完了後に `status` を `scheduled`、`scheduled_url` を予約後URLに更新する。

公開操作は、必ず対象runの `note_publish` へのユーザー明示承認と未使用claimを確認する。
