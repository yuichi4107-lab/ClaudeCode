---
name: ebook-from-theme
description: テーマ入力または添付素材からゼロから電子書籍本文を制作するフロントオーケストレーター。初回に選択式＋自由記述で制作条件を確認し、5層Webリサーチ→指定文字数（15,000/25,000/35,000字）の原稿（画像タグ付き）→ChatGPT/Codex側の画像生成→ebook-to-mangaが期待するproject.md＋manuscript/形式へ橋渡しするまでを一気通貫で実行する。ユーザーが「〇〇というテーマで電子書籍を作って」「Kindle本を書いて」などテーマから書籍本文の新規制作を依頼したときに使う（既存原稿のマンガ化はebook-to-manga）。
allowed-tools: Read, Write, Edit, Bash, Glob, WebSearch, WebFetch
---

# ebook-from-theme: テーマ起点電子書籍制作オーケストレーター

テーマまたは添付素材を受け取り、Phase 0〜4 の順に実行して `.company/outputs/ebooks/{slug}/` に成果物を生成し、最後に `ebook-to-manga` スキルへの引き渡し案内を出力する。

> **Codex側 `theme-to-ebook` との使い分け（意図的な別実装）**: 本スキルは Claude Code 側の実装で、既定 25,000字（15,000/25,000/35,000字）・`image_plan.json` 方式。Codex 側には別実装の `theme-to-ebook`（既定 100,000字・7パート構成・`progress.json` 方式）があり、Codex 側の親スキル `theme-to-ebook-to-manga` は `theme-to-ebook` を正本として使う。両者は実行環境の思想差（Claude=対話型、Codex=無人自律完走型）に基づく意図的な別実装であり、仕様を相互に同期しない（2026-07-07 オーナー承認）。

---

## Phase 0: 制作開始前の選択式質問＋自由記述

スキル起動直後、リサーチや原稿作成を始める前に、クリック式選択UIでユーザーの回答を待つ。`request_user_input` が使える場合はその選択カードを使う。使えない場合は `.company/scripts/ebook_setup_ui.py` のローカルクリック式フォームを起動する。Markdownの表や `1A、2B...` 形式を標準にしない。最後に自由記述が必要な場合は、UI側の `Other` またはクリック回答後の短い補足確認で受け取る。

**クリック式UIの出し方:**

1回目の `request_user_input`:

- `theme_handling`: テーマ
  - 依頼文のテーマで進める (Recommended)
  - 依頼文のテーマを少し広げて進める
  - 依頼文のテーマを絞り込んで進める
- `color_mode`: カラーモード
  - フルカラー (Recommended)
  - 白黒
- `character_setup`: キャラクター設定
  - 全部お任せ (Recommended)
  - 主人公だけ自分で用意
  - 全員自分で用意

2回目の `request_user_input`:

- `manga_pages_per_chapter`: 1章あたりの漫画ページ数
  - 4ページ (Recommended)
  - 3ページ
  - 5ページ
- `manga_position`: 漫画の配置位置
  - 章末 (Recommended)
  - 章頭
- `body_length`: 本文の文字数
  - 25,000字 (Recommended)
  - 15,000字
  - 35,000字

**回答処理ルール:**
- 未回答の項目のみ短く再質問する。
- ユーザーが「お任せ」「推奨で」「デフォルトで」と回答した場合は以下の推奨値を使う:
  - カラーモード: フルカラー
  - キャラクター設定: 全部お任せ
  - 1章あたりの漫画ページ数: 4ページ
  - 漫画の配置位置: 章末
  - 本文の文字数: 25,000字
- 選択値を変数として記録し、Phase 4 の `ebook-to-manga` 引き渡し案内に引き継ぐ。
- 自由記述は選択値より優先して、Phase 1 の検索クエリ、Phase 2 の構成、Phase 4 の `project.md` に反映する。
- ユーザーに `1A、2B...` のような長いコード型回答を要求しない。クリックで選ばせる。

**ローカルフォームの出し方（`request_user_input` が使えない場合）:**

```bash
python3 .company/scripts/ebook_setup_ui.py --theme "{テーマ}" --mode ebook-from-theme
```

保存先は `.company/outputs/ebook-setup-inputs/latest.json`。回答を読み取り、Phase 0回答として扱う。

---

## Phase 1: 5層リサーチ

Phase 0 の確定テーマと自由記述をもとにリサーチを実行し、以下2ファイルを出力する。原稿作成や構成設計より前に必ず実行する。

**出力パス:**
- `.company/outputs/ebooks/{slug}/_research/research.md`
- `.company/outputs/ebooks/{slug}/_research/meta.json`

### Step 1-0: slug 生成とディレクトリ作成

テーマから slug を生成する（例: 「言語化力」→ `gengo-ryoku`、「AI活用術」→ `ai-katsuyo`）。

```bash
mkdir -p ".company/outputs/ebooks/{slug}/_research"
mkdir -p ".company/outputs/ebooks/{slug}/_images_source/images"
mkdir -p ".company/outputs/ebooks/{slug}/manuscript"
```

### Step 1-1: 5層リサーチ（全層実行）

| Layer | 対象 | クエリ例 |
|-------|------|---------|
| 1 | YouTube専門家・解説動画 | `{テーマ} 解説 コツ site:youtube.com` |
| 2 | note専門家記事 | `{テーマ} note.com` |
| 3 | SNS/Xトレンド | `{テーマ} Twitter OR X 話題` |
| 4 | 市場・競合書籍 | `{テーマ} 本 おすすめ Amazon` |
| 5 | 読者の悩み・ニーズ | `{テーマ} できない 悩み 初心者` |

自由記述に業界、読者、避けたい切り口、必須論点が含まれる場合は、検索クエリにその語句を加える。

各層で WebSearch → 上位3件を WebFetch で詳細取得する。

### Step 1-2: research.md 生成

```markdown
# リサーチ結果: {テーマ}

## メタ情報
- テーマ: {テーマ}
- サブタイトル: {サブタイトル}
- 想定読者: {想定読者}
- 生成日: {日付}

## Layer 1: YouTube専門家の知見
...

## Layer 2: note記事の知見
...

## Layer 3: SNSトレンド
...

## Layer 4: 市場・競合分析
...

## Layer 5: 読者の悩み・ニーズ
...

## 総合まとめ
### 読者が本当に求めていること
### 差別化ポイント
### 重要キーワード
```

### Step 1-3: meta.json 生成

```json
{
  "slug": "{slug}",
  "title": "{タイトル}",
  "subtitle": "{サブタイトル}",
  "target_reader": "{想定読者}",
  "key_points": ["{ポイント1}", "{ポイント2}", "{ポイント3}"],
  "color_theme": {
    "primary": "#2D5BE3",
    "accent": "#FF8C42",
    "sub": "#00B4D8"
  }
}
```

`color_theme` はテーマの雰囲気・Phase 0 カラーモード選択に合わせて自動設定する。白黒選択時は `primary: "#333333"`, `accent: "#666666"`, `sub: "#999999"` を基本値とする。

---

## Phase 2: 原稿執筆（指定文字数・画像タグ付き）

**入力:** `_research/research.md`、`_research/meta.json`、Phase 0 項目6で選択した本文文字数

**出力パス:**
- `.company/outputs/ebooks/{slug}/_images_source/manuscript_raw.md`

### Step 2-1: 構成設計（目次自動生成）

Phase 0 項目6で選択した文字数に応じて、リサーチ結果から目次を生成する（いずれも全5章構成）:

| 選択文字数 | はじめに | 各章（×5章） | おわりに | 合計目安 |
|-----------|---------|------------|---------|---------|
| 15,000字 | 800〜1,000字 | 2,400〜2,800字 | 800〜1,000字 | 約15,000字 |
| 25,000字（推奨） | 1,200〜1,500字 | 4,000〜5,000字 | 1,200〜1,500字 | 約25,000字 |
| 35,000字 | 1,500〜2,000字 | 5,600〜6,400字 | 1,500〜2,000字 | 約35,000字 |

### Step 2-2: 原稿執筆ルール

- 文体: です・ます調で統一
- 1セクション（`###`）ごとに最低1枚の画像タグを挿入
- 章冒頭には必ず `HEADER_IMAGE` 画像タグを挿入
- 表・コードブロック・ASCII図は禁止（図解は画像タグで表現）
- 各章・節の前に `\newpage` を挿入

### Step 2-3: 画像タグ挿入形式

**章ヘッダー（各章冒頭）:**
```
<!-- [HEADER_IMAGE: pattern=illustration | title={章タイトル} | elements={主要トピック} | description={補足}] -->
```

**本文中図解（###ごと）:**
```
<!-- [INLINE_IMAGE: pattern={パターン名} | title={図解タイトル} | elements={要素1,要素2,...} | description={補足}] -->
```

**図解パターン（26種類）:**

| カテゴリ | パターン |
|---------|---------|
| 構造・分類 | tree, pyramid, layers, honeycomb, group |
| 流れ・変化 | flow-horizontal, flow-vertical, cycle, stairs, gantt |
| 比較・分析 | before-after, matrix, comparison-table, scale-circles, concentric, venn |
| 関係・論理 | network, radial, triangle, formula, map |
| 簡易・リスト | list-vertical, list-horizontal, list-dense |
| 特別 | illustration |

**完了条件:** 総文字数が Phase 0 で選択した文字数（±10%）。画像タグは文字数に比例した枚数（15,000字→18枚以上 / 25,000字→30枚以上 / 35,000字→42枚以上）。

---

## Phase 3: 挿絵生成（ChatGPT/Codex直生成）

**重要: 画像生成はAPI直叩きせず、このCodexセッション内でChatGPT/Codex側の画像生成経路により直接生成・保存・QCする。** `.company/codex/queue/` へのジョブ投入や別セッションへの引き渡しは行わない。

### Step 3-1: 画像タグ抽出とプロンプト変換

`manuscript_raw.md` から全画像タグを抽出し、以下のルールで生成プロンプトに変換する。

#### 共通スタイル指示（全画像に適用）

```
Japanese anime/manga style illustration, pop and cheerful mood.
Cute expressive anime characters with clearly readable emotions
(smiling, surprised, troubled, inspired), clean line art, bright vivid colors,
modern Japanese ebook illustration aesthetic.
Color palette: primary {meta.jsonのprimary}, accent {accent}, sub {sub}.
Background: white. {向き}.
All text in the image must be in Japanese (日本語).
Kindle電子書籍本文用。実在企業ロゴ・商標ロゴ禁止。
実写風・フォトリアル調、および無機質なピクトグラム/フラットインフォグラフィック調は禁止。
日本語テキストは大きく短く読みやすく。PNGとして保存。
```

#### 読者代理キャラクターの一貫性（全画像に適用）

Phase 3 開始時に、本のテーマ・想定読者に合わせて「読者代理キャラクター」1名（＋必要なら案内役キャラ1名）の外見設定を確定し、`image_plan.json` の `recurring_characters` に記録する。

- 例: `20代後半の女性会社員、黒髪ショートボブ、白いブラウス、丸みのある親しみやすいアニメ調デザイン`
- HEADER_IMAGE と illustration パターンには必ずこのキャラクターを登場させ、「悩み→気づき→実践→成長」という感情の変化を表情・ポーズで表現して読者の共感を誘う
- 図解系パターン（tree / flow / pyramid 等）も、レイアウトの明快さは保ちつつ、余白にデフォルメした読者代理キャラのリアクション（ひらめき・驚き・納得の表情）を小さく添えて、無機質な図にしない。ただし構造を伝える線・矢印・ラベルの視認性を最優先し、キャラクター装飾は図の隅・余白のみに配置する
- 全プロンプトにキャラクターの外見設定文を同じ文言で埋め込み、書籍全体で見た目を統一する

#### HEADER_IMAGE → 章ヘッダー横長（3:2 = 1536x1024px）

```
Chapter header illustration for Japanese ebook.
Large text reads "{章タイトル}" in bold Japanese.
VISUAL: {recurring_charactersの読者代理キャラ} が {章のテーマに沿った場面・感情} を体験しているアニメ調のシーン。{elements と description から構成}
STYLE: Japanese anime/manga style, pop and emotional, chapter header, landscape (3:2 ratio, 1536x1024px).
```

#### INLINE_IMAGE → パターン別変換

**サイズ選択ロジック:**
- デフォルト: 横長 3:2（1536x1024）
- 正方形（1024x1024）: list-vertical / pyramid / radial で要素が見やすい場合
- 縦長（1024x1536）: layers / list-vertical で要素数が多い場合

**★ 重要: 日本語テキストは絶対に英語に翻訳しない**
- `elements` 内の日本語 → `text reads "日本語のまま"` の形式で埋め込む
- title も `Title text reads "日本語タイトル"` で指定

| パターン | プロンプト構造 |
|---------|--------------|
| before-after | Left panel "Before" with text reads "{要素1}", right panel "After" with text reads "{要素2}" |
| flow-horizontal | Horizontal flow diagram with arrows: text reads "{要素1}" → text reads "{要素2}" → ... |
| stairs | Step-by-step staircase diagram, each step text reads "{要素N}" |
| radial | Central circle text reads "{タイトル}", surrounding nodes each text reads "{要素N}" |
| comparison-table | Card comparison layout, headers text reads "{要素1}" vs text reads "{要素2}" |
| cycle | Circular cycle diagram with nodes text reads "{要素N}" |
| pyramid | Triangle pyramid, top text reads "{要素1}", middle "{要素2}", base "{要素3}" |
| list-vertical | Vertical checklist, each item text reads "{要素N}" |
| tree | Tree/hierarchy diagram, root text reads "{タイトル}", branches text reads "{要素N}" |
| layers | Layered stack diagram, each layer text reads "{要素N}" |
| illustration | Japanese anime/manga style illustration depicting: {description}. Featuring the recurring reader character showing a relatable emotion |
| その他 | パターン名に応じた構図。タイトル・要素は text reads "日本語" 形式で指定 |

### Step 3-2: image_plan.json 作成

変換済みプロンプトを `.company/outputs/ebooks/{slug}/_images_source/image_plan.json` に保存する。`items` 配列に全画像の生成指示を直接入れる。

```json
{
  "generation_mode": "chatgpt_codex_direct_no_api",
  "book_title": "{meta.jsonのtitle}",
  "recurring_characters": [
    {"role": "読者代理", "appearance": "{外見設定（全プロンプト共通の文言）}"}
  ],
  "source_image_plan": ".company/outputs/ebooks/{slug}/_images_source/manuscript_raw.md",
  "final_image_dir": ".company/outputs/ebooks/{slug}/_images_source/images",
  "expected_count": {画像タグ総数},
  "items": [
    {
      "id": "{filename_stem}",
      "type": "diagram|illustration|header",
      "filename": "{filename}.png",
      "prompt": "{変換済みプロンプト}",
      "insert_file": "{挿入先章ファイル名}",
      "purpose": "{この画像が果たす役割}",
      "description": "{画像タグのdescriptionを日本語で}",
      "target_output": ".company/outputs/ebooks/{slug}/_images_source/images/{filename}.png"
    }
  ]
}
```

### Step 3-3: ChatGPT/Codex直生成

`image_plan.json` の `items` を上から順に処理する。

1. 各 item の `prompt` をChatGPT/Codex側の画像生成に投入する
2. 生成PNGを `target_output` に保存する
3. 生成直後に目視確認する
4. 日本語崩れ、細かすぎる文字、実在ロゴ、本文との不一致があればプロンプトを短くして再生成する
5. APIキー、OpenAI SDK、NanoBanana/Gemini API、`.company/codex/queue/` は使わない

### Step 3-4: 画像QCレポート

全画像生成後、`.company/outputs/ebooks/{slug}/_images_source/image_report.md` を作成する。

```markdown
# 画像生成レポート

## 方針
- API不使用
- ChatGPT/Codex側の画像生成経路で直接生成
- 別セッションへのジョブ引き渡しなし

## 生成結果
- 予定枚数: {N}
- 生成枚数: {N}
- 保存先: `_images_source/images/`

## 品質確認
- ファイル名一致
- 本文内容との対応
- 日本語テキストの可読性
- 実在企業ロゴ・商標なし
- アニメ・マンガ調のポップな画風（無機質なピクトグラム調になっていない）
- 読者代理キャラクターの見た目が全画像で統一されている
- 電子書籍内での統一感
```

### Step 3-5: manuscript.md 生成

`manuscript_raw.md` の画像タグを実画像リンクに置換して `manuscript.md` を生成する:

```
<!-- [HEADER_IMAGE: ...] --> → ![{章タイトル}](images/{filename}.png)
<!-- [INLINE_IMAGE: ...] --> → ![{図解タイトル}](images/{filename}.png)
```

**出力パス:** `.company/outputs/ebooks/{slug}/_images_source/manuscript.md`

---

## Phase 4: ebook-to-manga へのブリッジ

`meta.json` + `manuscript.md` を `ebook-to-manga` スキルが期待する入力形式に変換する。

**出力パス:**
- `.company/outputs/ebooks/{slug}/project.md`
- `.company/outputs/ebooks/{slug}/manuscript/` 配下に章別 .md ファイル

### Step 4-1: project.md 生成

`ebook-to-manga` の Step 1（ソース分析）が読み込む形式に準拠:

```markdown
# 電子書籍プロジェクト

## テーマ
{meta.jsonのtitle}が示すテーマの概要

## ターゲット
{meta.jsonのtarget_reader}

## タイトル・サブタイトル・著者名
タイトル: {meta.jsonのtitle}
サブタイトル: {meta.jsonのsubtitle}
著者名: {テーマ・内容・読者層に合った著者名（ペンネーム）を自動生成。ユーザーが著者名を指定した場合のみその値を使う}

## 章立て

はじめに
{はじめにの概要（1〜2文）}

第1章：{第1章タイトル}
{第1章の概要（1〜2文）}

第2章：{第2章タイトル}
{第2章の概要（1〜2文）}

第3章：{第3章タイトル}
{第3章の概要（1〜2文）}

第4章：{第4章タイトル}
{第4章の概要（1〜2文）}

第5章：{第5章タイトル}
{第5章の概要（1〜2文）}

おわりに
{おわりにの概要（1〜2文）}
```

**著者名は固定しない（お任せ）。テーマ・読者層に合うペンネームを自動生成する。ユーザーが著者名を明示指定した場合のみその値を使う。**

### Step 4-2: manuscript/ フォルダに章別 .md を生成

`manuscript.md` をファイル名順に読まれる形式で章別に分割して保存する。ファイル名は `ebook-to-manga` の Step 1 で読み込まれる順序を保証するため、ゼロ埋め連番プレフィックスを付ける:

```
.company/outputs/ebooks/{slug}/manuscript/
├── 00-はじめに.md
├── 第1章_{タイトル}.md
├── 第2章_{タイトル}.md
├── 第3章_{タイトル}.md
├── 第4章_{タイトル}.md
├── 第5章_{タイトル}.md
└── 06-おわりに.md
```

**注記:** ebook-to-manga Step 1 はファイル名順（辞書順）に原稿を読み込む。実例 `01-worker-positive` と同一の命名規則（`00-はじめに` / `第N章_タイトル` / `06-おわりに`）に揃えれば既存運用と一致する。

各ファイルの内容は `manuscript.md` から該当章を抜き出したもの（画像リンク含む）。

### Step 4-3: 引き渡し案内の出力

ブリッジ完了後、以下の情報を含む引き渡し案内を出力する:

```
ebook-to-manga でマンガ化できる状態になりました。

【ソースフォルダ】
.company/outputs/ebooks/{slug}/

【ebook-to-manga 起動時の引数情報】
- ソースフォルダ: .company/outputs/ebooks/{slug}/
- 目標ページ数: {Phase0選択章数} × {Phase0選択ページ数/章} = {合計}ページ
- カラーモード: {Phase0で選択した値（フルカラー/白黒）}
- キャラクター設定: {Phase0で選択した値}
- 漫画の配置位置: {Phase0で選択した値（章末/章頭）}
- 自由記述メモ: {Phase0自由記述の要約}
- ジャンル指定: 未指定（自動判定）

次のステップ:
/ebook-to-manga を起動し、ソースフォルダとして上記パスを指定してください。
```

自動連鎖はしない。手動でユーザーが `ebook-to-manga` を起動する。

---

## 実行フロー早見表

```
Phase 0: 選択式質問＋自由記述 → 回答待ち
    ↓ 回答確定
Phase 1: 5層リサーチ → research.md + meta.json
    ↓
Phase 2: 原稿執筆 → manuscript_raw.md（Phase0選択文字数・画像タグは文字数に比例）
    ↓
Phase 3-1〜2: 画像タグ→プロンプト変換 → image_plan.json作成
    ↓
Phase 3-3〜4: ChatGPT/Codex直生成 → 画像QCレポート
    ↓
Phase 3-5: manuscript.md 生成
    ↓
Phase 4-1〜2: project.md + manuscript/章別.md 生成
    ↓
Phase 4-3: ebook-to-manga 引き渡し案内を出力
```

---

## 制約（厳守）

- インラインAPI直叩き（`client.images.generate` 等）を一切記述・実行しない
- `.company/codex/queue/` へのジョブ投入や別セッションへの画像生成ハンドオフは行わない
- 著者名は固定しない。お任せ（自動生成）を既定とし、ユーザー指定があればそれを優先する
- `HANDOFF_MODE=codex-handoff` や `.company/handoff/codex-image-gen/_spec/SPEC.md` は実在しないため参照・依存しない
- `ebook-to-manga` skill.md は変更しない
- ターミナルへの大量出力禁止（CLAUDE.md ターミナル出力制限準拠）
