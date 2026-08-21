---
name: ebook-to-manga
description: 既存のKindle電子書籍（Markdown原稿）をマンガ形式に変換し、EPUB化してKDP出版用メタデータまで一括生成するスキル。ChatGPT Images 2.0 (gpt-image-2) 画像生成、コミクル2.0テンプレートを組み合わせた8ステップパイプライン。
---

# 電子書籍マンガ化スキル (Ebook-to-Manga Converter)

## 概要

このスキルは、既存のKindle電子書籍（Markdown原稿）をマンガ形式の電子書籍に変換する。
8ステップのパイプラインでソース分析からKDP出版準備まで一気通貫で実行する。

## 最優先ルール: 画像生成でAPIを使わない

2026-06-02以降、このワークスペースでは画像生成に **OpenAI API / `OPENAI_API_KEY` / `openai-image-gen` / `client.images.generate` / `client.images.edit` を使わない**。

- 画像生成は **ChatGPT Images 2.0（Codex/ChatGPT側の画像生成経路）** で行う。
- Codexで作業中の場合、`.company/codex/queue/` への引き渡しを作らず、このCodexセッション内でそのまま生成・保存・QC・EPUB反映まで進める。
- 以前のAPI直呼び運用は廃止済み。画像生成ではAPIキー確認もSDK呼び出しも行わない。
- 日本語文字を画像内に入れる場合も、まず ChatGPT Images 2.0 で生成する。文字崩れが大きい場合はユーザーに確認して再生成する。

## 入力

- **ソースフォルダ**（必須）: ebookフォルダのパス（例: `.company/outputs/ebooks/01-worker-positive/`）。`project.md` と `manuscript/` ディレクトリを含むこと。
- **目標ページ数**（任意）: デフォルト100。範囲40-120。
- **ジャンル指定**（任意）: 作画設定の20ジャンルから指定。未指定時は書籍テーマから自動判定。
- **出力フォルダ名**（任意）: `.company/outputs/ebooks-manga/` 配下。デフォルトはソースフォルダ名。

## 前提条件

- ChatGPT Images 2.0 を利用できる Codex/ChatGPT 画像生成環境であること（必須）
- `OPENAI_API_KEY` は不要。設定確認もしない。
- `openai` Pythonパッケージは画像生成には使わない。
- Python 3.x が `python` コマンドで利用可能なこと（Windows環境）
- `GOOGLE_AI_STUDIO_API_KEY` / `google-genai` も使わない。

## 画像生成の実行モード（HANDOFF_MODE）

本スキルの画像生成は、現在は **ChatGPT Images 2.0 直生成モード** を標準とする:

- **標準**: このCodexセッション内で ChatGPT Images 2.0 により生成し、保存・QC・EPUB反映まで行う。
- **旧 `HANDOFF_MODE=codex-handoff` 相当**: 別セッションへのキュー引き渡しは作らず、同じ考え方をこのCodex内で実行する。
- **旧 `HANDOFF_MODE=inline`**: OpenAI API直呼びモードなので使用禁止。

モード切替が必要な場合も、API直呼びには戻らない。
Step 3（キャラデザイン）も ChatGPT Images 2.0 経路で生成する。

ハンドオフ仕様の詳細: `.company/codex/_spec/SPEC.md`

---

## 画像生成の絶対ルール

- **全ステップ共通**: 画像生成時は必ず「日本のアニメ・マンガ調イラスト」で生成すること
- 実写風・フォトリアル風の画像は禁止
- プロンプトの冒頭に必ず「◆【絶対最優先】必ず日本のアニメ・マンガ調のイラストで描いてください。実写風・フォトリアル風は禁止です。」を含めること
- これはキャラクターデザイン（Step 3）、ページ画像（Step 5）、表紙（Step 6）すべてに適用する

## 画像フォーマット

- **Step 5 本文ページ画像は、生成直後のPNGを原本として残し、KDP用EPUBには同寸法のJPEG版（`.jpg`）を使用する**
  - 生成画像の受け取り・QC・監査用: `page_{NNN}.png`
  - EPUB製本用: `page_{NNN}.jpg`
  - JPEG変換時は文字のにじみを避けるため、品質85〜92を目安にし、必ず目視またはOCRで可読性を確認する
- **Step 6 表紙は PNG をマスターとして保存し、同寸法の JPEG 版 `cover.jpg` も必ず保存する**（KDP申請では `cover.jpg` を優先）
- Step 3 キャラリファレンス画像はPNG形式（変更なし）

## 分冊対応

ページ数が多い場合（目安: 80P超）は、複数巻に分冊する。

### 分冊時の出力ディレクトリ構成

```
.company/outputs/ebooks-manga/{book-name}/
├── manuscript/                     # 共通素材（全巻共有）
│   ├── シナリオ.txt
│   ├── character_defs.json
│   └── characters/
│       ├── {charA}.png ... 
├── vol1/                           # 第1巻
│   ├── panels/
│   │   └── comicle_output.csv
│   ├── pages/
│   │   ├── page_001.png ... page_NNN.png
│   └── KDP出版用/
│       ├── {タイトル} 第1巻.epub
│       ├── cover.png
│       └── cover.jpg
├── vol2/                           # 第2巻
│   ├── panels/
│   │   └── comicle_output.csv
│   ├── pages/
│   │   ├── page_001.png ... page_NNN.png
│   └── KDP出版用/
│       ├── {タイトル} 第2巻.epub
│       ├── cover.png
│       └── cover.jpg
├── ...
└── progress.json
```

### 単巻の出力ディレクトリ構成

```
.company/outputs/ebooks-manga/{book-name}/
├── project.md
├── KDP出版用/
│   ├── {タイトル}.epub
│   ├── cover.png
│   ├── cover.jpg
│   ├── 書籍情報.md
│   ├── ジャンル・キーワード.md
│   └── 書籍紹介文_HTML.html
├── manuscript/
│   ├── シナリオ.txt
│   ├── character_defs.json
│   └── characters/
│       ├── {charA}.png ... 
├── panels/
│   ├── comicle_output.csv
│   └── pages/
│       ├── page_001.png ... page_NNN.png
└── progress.json
```

### 標準保存ルール（全電子書籍共通）

| フォルダ | 内容 | 備考 |
|---------|------|------|
| `project.md` | プロジェクト概要 | タイトル、ターゲット、章立て、ステータス |
| `KDP出版用/` | KDPアップロードに必要な全ファイル | EPUB、表紙、書籍情報、紹介文HTML |
| `manuscript/` | 原稿・制作素材 | 章別Markdown、シナリオ、キャラ定義等 |

**書籍情報.md のフォーマット（必須）:**
```markdown
# 書籍情報

## タイトル
- **日本語**: {タイトル}
- **フリガナ**: {カタカナ}
- **ローマ字**: {ローマ字}

## サブタイトル
- **日本語**: {サブタイトル}
- **フリガナ**: {カタカナ}
- **ローマ字**: {ローマ字}

## 著者名
- **日本語**: {著者名}
- **フリガナ**: {カタカナ}
- **ローマ字**: {ローマ字}

## 出版社名
- **日本語**: YN出版
- **フリガナ**: ワイエヌシュッパン
- **ローマ字**: YN Shuppan
```

**書籍紹介文_HTML.html（必須）:**
KDP商品説明欄にそのまま貼り付けられるHTML形式。以下の構成で作成する:
1. `<h2>` フック（読者の悩みに刺さる一文）
2. `<ul>` 共感リスト（こんな悩みはありませんか？）
3. `<h3>` + `<p>` 解決策の提示
4. `<h3>` + `<ul>` 本書で得られること
5. `<h3>` + `<ul>` こんな方におすすめ
6. `<h3>` + `<p>` CTA（行動を促す一文）
7. `<h3>` + `<ul>` 目次

## 実行順序と依存関係

**フル実行時の正しい順序:**
```
Step 1（ソース分析）→ Step 2（シナリオ）→ Step 3（キャラデザ）
→ Step 4（CSV作成）→ Step 5（画像生成）→ Step 6（表紙作成）
→ Step 7（EPUB製本）→ Step 8（メタデータ）
```

**重要: Step 7（EPUB製本）は、Step 5（画像）とStep 6（表紙）の両方が完了してから実行すること。**
表紙なしでEPUBを作ると、後から表紙を差し替える手間が発生する。

## 部分実行への対応

| リクエスト | 実行ステップ | 前提条件 |
|-----------|------------|---------|
| 「○○をマンガ化して」 | Step 1-8 フル実行 | - |
| 「シナリオだけ作って」 | Step 1-2 | - |
| 「キャラデザインして」 | Step 3のみ | シナリオ必須 |
| 「コマ割りCSVを作って」 | Step 4のみ | シナリオ+キャラ必須 |
| 「画像を生成して」 | Step 5のみ | CSV必須 |
| 「表紙だけ作って」 | Step 6のみ | キャラ定義必須 |
| 「EPUBにまとめて」 | Step 7のみ | **画像+表紙の両方が必須** |
| 「メタデータだけ生成して」 | Step 8のみ | - |

---

## ワークフロー

### Step 1: ソース分析と準備

1. ソースフォルダから `project.md` を読み込み、書籍メタ情報を抽出する:
   - タイトル、サブタイトル、著者名
   - ターゲット読者
   - 章構成

2. `manuscript/` 配下の全 `.md` ファイルをファイル名順に読み込み、以下を集計する:
   - 章数、各章の行数・文字数
   - 総文字数

3. **ジャンル自動判定**: 書籍テーマ・内容から「作画設定マスタ」（後述）の20ジャンルの中で最適なものを選択する。判定基準:
   - 書籍タイトル・サブタイトルのキーワード
   - 章の内容からのテーマ推定
   - ユーザーが明示指定した場合はそちらを優先

4. 出力ディレクトリを作成する:
   ```bash
   mkdir -p ".company/outputs/ebooks-manga/{book-name}/KDP出版用"
   mkdir -p ".company/outputs/ebooks-manga/{book-name}/manuscript/characters"
   mkdir -p ".company/outputs/ebooks-manga/{book-name}/panels/pages"
   ```

5. `progress.json` を作成して進捗管理を開始する:
   ```json
   {
     "book_name": "{book-name}",
     "source_path": "{ソースパス}",
     "target_pages": 100,
     "genre": "{選択ジャンル}",
     "steps": {
       "1_source": {"status": "done"},
       "2_scenario": {"status": "pending"},
       "3_characters": {"status": "pending"},
       "4_panels": {"status": "pending"},
       "5_images": {"status": "pending", "completed": 0, "total": 0, "failed": []},
       "6_cover": {"status": "pending"},
       "7_epub": {"status": "pending"},
       "8_metadata": {"status": "pending"}
     }
   }
   ```

6. **ユーザーに提示**: ソース分析レポート（タイトル、章構成、選択ジャンル、推定ページ数）を表示し、確認を得る。

---

### Step 2: マンガ用シナリオ作成

以下のペルソナと指示に基づいて、Claudeがマンガ用シナリオを作成する。

#### ペルソナ設定
- ビジネス関連の超人気売れっ子漫画シナリオライター
- どんなテーマのビジネスにおいても人気大爆発の漫画のシナリオを作成することのできる、独創的で斬新奇抜なアイディアを持っている
- 豊富な語彙力、情感豊かな表現力によってターゲット読者の心を動かし、彼らの問題を解決する類稀な能力を持っている
- 書籍テーマについての実践的なスキルを持っていて、それをもとに漫画のストーリーを書くことができる

#### シナリオ作成ルール
1. 書籍原稿の各章に沿って漫画ストーリーを作成する
2. 登場人物は**最大3人**に設定する
3. 登場人物は見分けやすいよう**年齢・性別をバラバラ**にする
   - NG例: 20代女性を2人登場させる
   - OK例: 20代女性と20代男性、または20代女性と40代男性
4. **1コマ単位の記述ではなく文章形式**で記載する
5. 章立ては書籍の章構成をそのまま踏襲する

#### 出力フォーマット例
```
「{タイトル} ～{サブタイトル}～」

プロローグ：{プロローグタイトル}
{プロローグの文章形式シナリオ}

第1章：{章タイトル}
{第1章の文章形式シナリオ}

第2章：{章タイトル}
{第2章の文章形式シナリオ}

...

エピローグ：{エピローグタイトル}
{エピローグの文章形式シナリオ}
```

#### 出力
- ファイル: `manuscript/シナリオ.txt`
- **ユーザー確認ポイント**: シナリオの内容を表示し、登場人物・ストーリー展開の確認を得る

---

### Step 3: キャラクターデザイン

シナリオの登場人物（最大3名）ごとにキャラクターデザインを生成する。

> Step 3 は HANDOFF_MODE に関わらず常に Claude Code が inline で実行する（キャラ参照画像は Step 5-A で queue/<job-id>/characters/ にコピーして Codex に渡す）。
> フロー: 3-1 → 3-2-A（直接生成）→ 3-3 ユーザー確認

#### 3-1. キャラクター定義の作成

シナリオから各登場人物の以下を決定し、`manuscript/character_defs.json` に保存する:
```json
{
  "{キャラA名}": "{キャラA名}: {年齢}{性別}、{髪型}、{髪色}、{体型}、{デフォルト服装の詳細}",
  "{キャラB名}": "{キャラB名}: {年齢}{性別}、{髪型}、{髪色}、{体型}、{デフォルト服装の詳細}",
  "{キャラC名}": "{キャラC名}: {年齢}{性別}、{髪型}、{髪色}、{体型}、{デフォルト服装の詳細}"
}
```

#### 3-1a. 時間経過によるキャラクターバリエーション

ストーリー中で時間が経過し、キャラクターの容姿が変化する場合（子供の成長、髪型の変化、加齢など）は、**同一キャラクターの時期別バリエーション**として別定義・別リファレンス画像を作成する。

例:
```json
{
  "ひなた（赤ちゃん期）": "ひなた: 0〜1歳の女の子、柔らかい黒髪（少なめ）、丸い大きな目、ピンクのロンパース",
  "ひなた（2歳期）": "ひなた: 2歳の女の子、短い黒髪のおかっぱ、丸い大きな目、ピンクのTシャツに白いズボン"
}
```

- キャラ名に `（時期名）` を付けて区別する
- リファレンス画像も時期ごとに別ファイルで生成する（例: `ひなた_赤ちゃん期.png`, `ひなた_2歳期.png`）
- CSVでは該当時期のリファレンス画像を参照する: `添付のひなた_2歳期.pngと100%同一の外見で描画`
- ストーリー上の時期に応じて正しいバリエーションを使い分けること

#### 3-1b. 場面別服装ルールの定義（outfit_id 参照方式）

キャラクターの服装は場面（シーン）に応じて変化させる。ストーリーの状況に合った服装を設定し、**同じシーン内ではページが変わっても服装を統一する**。

服装管理は `character_defs.json` に `outfit_presets` オブジェクトを追加する方式を使用する。CSV側は `outfit_id` 列でプリセットを参照し、`gen_manga_bundle.py` 等が `character_defs.json` を読んで description を展開する。

##### outfit_presets の仕様

**outfit_id の命名規則**: `{キャラ名snake_case}_{シーン略称}`（例: `misaki_casual`, `misaki_work_home`）

**1キャラあたり2〜4プリセット推奨**（多すぎると管理コスト増）

**各プリセットのフィールド**: `character`（キャラ名）、`description`（服装詳細文字列）、`scenes`（適用シーン例の配列）

**character_defs.json の拡張例:**
```json
{
  "キャラ定義（既存）": "...",
  "outfit_presets": {
    "misaki_casual": {
      "character": "ミサキ",
      "description": "ボーダー柄（白と紺）のカットソーにデニムパンツ、白いスニーカー（自宅・外出の普段着）",
      "scenes": ["自宅", "外出", "カフェ", "公園"]
    },
    "misaki_work_home": {
      "character": "ミサキ",
      "description": "グレーのスウェット上下、素足（在宅作業・深夜集中タイム）",
      "scenes": ["在宅作業", "深夜", "早朝"]
    }
  }
}
```

**CSVでの服装指定ルール:**
1. CSV の `outfit_id` 列（5列目）に、そのページで適用するプリセットIDを記載する（例: `misaki_casual`）
2. **同じシーン（場面転換がないページ連続）では同じ outfit_id を維持する**
3. 場面が変わったら（時間帯・場所の変化）適切な outfit_id に切り替える
4. 夜のシーンで部屋着/パジャマ → 翌朝のシーンで普段着、のように自然に遷移させる
5. テキストページの `outfit_id` は空文字 `""` を格納する

#### 3-2-A: キャラクタープロンプト構築（共通）

各キャラクターについて、gpt-image-2 で全身リファレンス画像を生成するためのプロンプトを組み立てる。

**画像生成プロンプトの構成**:
```
◆【絶対最優先】必ず日本のアニメ・マンガ調のイラストで描いてください。実写風・フォトリアル風は禁止です。
◆作画スタイル: 日本のアニメ・マンガ調イラスト、クリーンな線画、デジタル彩色、はっきりした輪郭線
{Step 1で選択したジャンルの作画設定全文}

キャラクターデザイン:
{キャラ名}: {character_defs.jsonの外見詳細}

# 補足
- 必ず日本のアニメ・マンガ調のイラストで描いてください。実写風・フォトリアル風は禁止
- セリフやオノマトペは入れない
- 全身の立ち姿にしてください
- 小道具を手に持たせないでください
- 白背景
```

#### 3-2-B: 生成実行（ChatGPT Images 2.0直生成）

APIは使わない。`OPENAI_API_KEY`、OpenAI SDK、`openai-image-gen`、`client.images.generate/edit` は使用禁止。

1. 上記のキャラクターデザインプロンプトを ChatGPT/Codex 側の画像生成機能に渡す
2. 生成サイズは 2:3 縦長（目安: 1024x1536）、高品質を指定する
3. 生成されたPNGを `manuscript/characters/` に保存する
4. ファイル名は `{キャラID}_{YYYYMMDD_HHMMSS}.png` 形式にする
5. 生成後、Read/Viewで表示し、白背景・全身・日本のマンガ調・文字なしを確認する

旧 `HANDOFF_MODE=inline` / `HANDOFF_MODE=codex-handoff` のAPI実行手順は使わない。Codexで作業している場合は、このセッション内で生成・保存・QCまで進める。

**3-2-C: 受け取りと後処理:**

inline 生成のため不要。生成完了後そのまま 3-3 ユーザー確認へ進む。

#### 3-3. ユーザー確認
- 生成されたキャラクター画像をReadツールで表示する
- ユーザーの承認を得てから次のステップへ進む
- 不満があれば外見設定を修正して再生成する

---

### Step 4: コマ割りCSV作成

**重要: 既存の `generate_comicle_csv.py` は使用しない。Codex自身がCSVを直接生成する。**

シナリオ + キャラクター定義 + 作画設定をもとに、コミクル用CSVを生成する。

#### CSV仕様
- **ヘッダー**: `ページ番号,使用するコマ割りテンプレ,漫画作成のプロンプト,コマ別テキストJSON,outfit_id`
- **目標ページ数**: 入力で指定された値（デフォルト100）
- **出力**: `panels/comicle_output.csv`

#### コマ別テキストJSON 仕様

4列目 `コマ別テキストJSON` には、後工程の Blind-OCR 比較が期待テキストを
直接参照できるよう、ページ内の全セリフ・ナレーションを JSON 配列として格納する。

5列目 `outfit_id` には、そのページで適用する服装プリセットIDを格納する。
テキストページは空文字 `""` を格納する（`gen_manga_bundle.py` 等が `character_defs.json` の
`outfit_presets` を参照して description を展開する）。

**設計の注意（重要）**: この列は画像生成（Gemini）には渡さない。
OCR 判定だけが参照する。画像生成プロンプト（3列目）と内容が重複するが、
生成側に見せることで confirmation bias が生じるため意図的に分離している。

**JSON スキーマ:**
```json
[
  {"panel_id": 1, "type": "dialogue",  "speaker": "キャラ名", "text": "セリフ本文"},
  {"panel_id": 1, "type": "narration", "speaker": null,       "text": "ナレーション本文"},
  {"panel_id": 2, "type": "dialogue",  "speaker": "キャラ名", "text": "セリフ本文"},
  ...
]
```

**フィールド仕様:**

| フィールド | 型 | 許容値 | 説明 |
|---|---|---|---|
| `panel_id` | 整数 | 1 以上の整数 | コマ番号（読み順：右→左 / 上→下の順に採番） |
| `type` | 文字列 | `"dialogue"` または `"narration"` のみ | セリフ・吹き出しは `"dialogue"`、ナレーションボックスは `"narration"` |
| `speaker` | 文字列 or null | キャラ名文字列 / `null` | `"dialogue"` 時は発話者名（例: `"ミサキ"`）、`"narration"` 時は必ず `null` |
| `text` | 文字列 | — | プロンプトの「」内セリフ・ナレーション本文と完全一致する文字列。OCR 比較の基準値。**1コマあたり平均50字程度を目安**（soft limit、超過率10%未満が望ましい） |

**対象外（含めないもの）:**
- オノマトペ（ぱぁっ / ビクッ 等）— OCR 対象外
- 背景テキスト・看板・スマホ画面等 — OCR 対象外

**複数セリフ・複数ナレーションの扱い:**
1コマ内に複数のセリフ・ナレーションがある場合は、コマ読み順（右→左）に
**別オブジェクトとして配列に追記**する（セパレータ結合は使用しない）。

例（1コマに2セリフ）:
```json
[
  {"panel_id": 1, "type": "dialogue", "speaker": "ミサキ", "text": "えっ、本当に？"},
  {"panel_id": 1, "type": "dialogue", "speaker": "ケンタ", "text": "ああ、間違いない"}
]
```

**テキストページ（テンプレ=テキストページ）の扱い:**
- `コマ別テキストJSON` は空配列 `[]` を格納する
- `panel_id` の採番は不要（テキストページに panel_id は存在しない）
- 画像生成もスキップ対象のため、OCR 判定も実施しない

**テンプレと panel_id の対応:**

| テンプレ | コマ数 | panel_id の値 | 補足 |
|---------|--------|--------------|------|
| テンプレ1 | 1 | 1 | — |
| テンプレ2〜4 | 2 | 1, 2 | 1=上段（または右側）、2=下段（または左側） |
| テンプレ5 | 3 | 1, 2, 3 | 1=上段、2=中段、3=下段 |
| テンプレ6 | 3 | 1, 2, 3 | 1=上段、2=下段右側、3=下段左側 |
| テンプレ7 | 3 | 1, 2, 3 | 1=上段右側、2=上段左側、3=下段 |

#### 7種類のコマ割りテンプレート

テンプレート参照画像: `G:\マイドライブ\AIC\コミクル2.0\テンプレ\テンプレ1-7.jpg`

| テンプレ | コマ数 | 構成 | 読み順 |
|---------|--------|------|--------|
| テンプレ1 | 1コマ | ページ全体を使った1コマ | — |
| テンプレ2 | 2コマ | 上下に均等2分割 | 上段→下段 |
| テンプレ3 | 2コマ | 上下2分割（上段小→下段大） | 上段→下段 |
| テンプレ4 | 2コマ | 上下2分割（上段大→下段小） | 上段→下段 |
| テンプレ5 | 3コマ | 上・中・下の3段構成 | 上→中→下 |
| テンプレ6 | 3コマ | 上段1コマ + 下段左右2コマ | 上段→下段右側→下段左側 |
| テンプレ7 | 3コマ | 上段左右2コマ + 下段1コマ | 上段右側→上段左側→下段 |

#### コマ読み順と配置ルール
- 読み順: 日本の漫画形式（**右上から左下へ**）
- 横並びのコマの場合: 必ず「右側」が先のコマ、「左側」が後のコマ
  - 例: 1コマ目＝右側、2コマ目＝左側

#### 各ページのプロンプト構造（出力フォーマット）

以下の順序と書式で記述する。コマの位置指定（右側・左側）を間違えないこと。

```
◆【注意】【】で囲まれた単語は感情や状況の指示であり、画像内に文字として描画しないでください
◆【絶対最優先】必ずフルカラーにしてください
◆【絶対最優先】必ず日本のアニメ・マンガ調のイラストで描いてください。実写風・フォトリアル風は禁止です。
◆【絶対最優先】キャラクター外見: [キャラ名]は添付の[ファイル名]と100%同一の外見で描画
◆【出力サイズ】2:3
◆【補足情報】上下左右に50ピクセルの余白を設けてください
◆【補足情報】服装: [服装詳細]
◆【コマ構成】[テンプレ名]: [コマ数と配置の詳細]
◆【作画】[作画設定マスタから読み込んだジャンル別作画スタイル全文（省略せず100%書き写す）]
◆【ストーリー】
[各コマの詳細描写]
```

#### ストーリー部分の記述ルール

各コマについて以下を記述する:
```
Nコマ目 (位置): [シーン描写] セリフ: [セリフ内容] ナレーション: [ナレーション] オノマトペ: [オノマトペ]
```

- **シーン描写**: 誰が何をしているか具体的に記述。表情、感情表現、ポーズ、構図を詳細に描写
- **セリフ**: 形式: `［発言者］の吹き出しに「セリフの内容」`
- **ナレーション**: 四角い吹き出し（ナレーションボックス）。形式: `ナレーション: ［四角枠］テキスト内容`
  - 場面転換（「その夜——」）、状況説明、心理描写に使用する
  - ナレーションなしの場合: `ナレーション: なし`
- **背景**: シーンの感情に合わせて適切なパターンを選択
  - 水玉模様、半円、ドット模様、フラッシュエフェクト、ストライプ、グラデーション、幾何学模様など
- **オノマトペ**: ストーリーに応じて以下から選択
  - ぱぁっ / パァァ / ビクッ / ギクッ / キュン / イライラ / じーっ / ガーン / むすっ / テクテク / ダダダダ / ガチャ / チラッ

#### 原文テキストの活用（最重要）

**原稿のテキストをできるだけ忠実にCSVに反映すること。**

1. **セリフ「」は全て省略せずCSVに含める** — 原稿にあるセリフは1つも落とさない
2. **地の文はナレーションボックスとして積極的に入れる** — 場面転換・状況説明・心理描写をナレーション欄に配置
3. **テキスト密度目標: 1ページあたり約90文字**（セリフ+ナレーション合計）
4. **原稿カバー率80%以上を目指す** — CSV内のセリフ+ナレーション文字数 ÷ 原稿の全テキスト文字数

テキスト密度が低い（70字/P以下）場合はナレーションの追加が不足している。密度を計測して調整すること。

#### 1コマあたりの文字数目安（50字 soft limit）

1コマあたりのセリフ＋ナレーション合計は **平均50字程度を目安** とする。

- **hard limit ではない**（長セリフの多少超過は許容する）
- **超過率10%未満**（50字超過コマ数 / 全コマ数 < 10%）を望ましい水準とする
- 1ページあたりのテキスト密度目標（約90文字）と合わせて確認すること
- 50字を大幅に超える長セリフは、自然な切れ目で次コマに分割することを優先する
- 1コマ30字以下の旧 hard limit は廃止（過剰なコマ分割を抑制し、ページ数の自然な圧縮を狙う）

#### CSV生成時の注意事項
- キャラクター統一性を最優先とし、画像参照を厳密に適用
- コマ構成はテンプレートに完全準拠し、コマ数の変更は一切禁止
- 各ページで一貫した作画スタイルを維持
- 複数キャラクター登場時は位置関係と向きを明確に指定
- 各コマの状況説明は「誰が何をしているか」を具体的に記述
- カラーで生成すること。モノクロの生成は禁止
- **作画設定の演出欄に「ステップ図解」は入れない**（STEP1→STEP2のような図が多発するため）
- 文字列内に"ダブルクォート"を使う場合は〝〟に置き換える（CSVフォーマット崩れ防止）
- **`コマ別テキストJSON` 列のフォーマット対策（重要）**:
  - JSON 内の文字列値（`text` / `speaker` フィールド）に `"` が含まれる場合も〝〟に変換する
  - テキスト内に `,`（カンマ）が含まれる場合は、`コマ別テキストJSON` 列全体を CSV の
    標準ダブルクォートで囲む（例: `"[{""panel_id"": 1, ...}]"`）。
    ただし JSON 内で〝〟変換済みの場合はネストが崩れないため、
    **列の値全体をダブルクォートで囲む方法を推奨する**
  - `text` フィールド内に改行文字（`\n`）は使用しない。改行が必要な場合は空白区切りで1行に収める

#### 前付けページ（必須）

CSVの先頭に以下の前付けページを必ず含めること:

| ページ | テンプレ | 内容 | 全巻 | 2巻以降 |
|--------|---------|------|------|---------|
| 目次 | テキストページ | 巻タイトル＋収録話一覧＋コラム一覧 | ✅ | ✅ |
| 登場人物紹介 | テンプレ1 | キャラクターを縦に並べ全身イラスト＋名前＋一行紹介 | ✅ | ✅ |
| 前巻までのあらすじ | テキストページ | 前巻の物語要約（200-300字） | - | ✅ |

#### 後付けページ（必須）

CSVの末尾（本編終了後）に以下の後付けページを必ず以下の順序で含めること:

| 順序 | ページ | テンプレ | 内容 | 全巻 |
|------|--------|---------|------|------|
| 1 | 著者紹介 | テキストページ | 著者プロフィール（肩書き＋経歴＋連絡先） | ✅ |
| 2 | **CTA（固定）** | **画像ページ（固定アセット）** | **`.claude/skills/ebook-to-manga/assets/cta.png` を全巻共通で必ず差し込む** | ✅ |
| 3 | 奥付 | テキストページ（colophon） | 書名／著者／発行所／発行日／著作権表示 | ✅ |

> **CTA画像の固定運用**: CTAページは全巻共通の固定画像（`.claude/skills/ebook-to-manga/assets/cta.png`、1024×1536 PNG）を使用する。CSVには載せず、Step 7（EPUB製本）で著者紹介ページ直後・奥付ページ直前に必ず spine に挿入する。差し替えはこのアセットファイル自体を更新することで全巻に反映される。

#### コラムページ

原稿にコラムがある場合、テキストページとして原文をそのまま入れる:
```
◆【テキストページ】このページは画像生成不要。EPUB製本時にテキストとして直接レンダリングする。
◆【コラム原文】
[原稿のコラム全文をそのまま入れる]
```
長いコラムは段落の区切りで2ページに分割する。

#### テンプレート選択の目安
- テンプレ1（1コマ）: タイトルページ、インパクトシーン、感情的クライマックスに使用。全体の15-20%
- テンプレ2-4（2コマ）: 会話シーン、対比表現に使用。全体の30-40%
- テンプレ5-7（3コマ）: ストーリー展開、場面転換に使用。全体の40-50%

#### ユーザー確認
- CSV生成後、以下を表示して確認を得る:
  - 総ページ数
  - テンプレート分布（各テンプレの使用割合）
  - 最初の3ページ、中盤の1ページ、最後の1ページのプロンプトサンプル

---

### Step 5: 画像生成（ハイブリッドQCループ）

#### 概要

Blind-OCR 判定と Vision-check を組み合わせた QC ループで全ページのテキスト正確性を高める。
`max_iter` 回連続 FAIL 時は該当ページを `blocked_gpt_image2_web` として止め、解消するまで EPUB 化へ進まない。

- **A路線**: 画像生成 → Blind-OCR → プログラム比較 → PASS なら完了
- **max_iter 超過時**: 最終プロンプトを `prompts/page_{NNN}_blocked_prompt.txt` に保存し、`progress.json` の `blocked_pages` / `blocked_reasons` に記録する。該当ページを最終成果物にせず、`blocked_pages` が空になるまで Step 7（EPUB製本）に進まない。

リファレンス実装: `.company/outputs/ebooks-manga/manga-career-restart/_prototype/hybrid_loop.py`（465行）

> **モード別フロー概要**
>
> - `inline` モード: 各 iter で [A-1] 直接 API 呼び出し → [A-2] Blind-OCR → [A-3] Vision-check → 判定 → PASS or 次 iter / `blocked_gpt_image2_web`
> - `codex-handoff` モード: Claude が `.company/codex/queue/<job-id>/` にバンドル（Step 5 全ページ + Step 6 表紙）を 1 回投入するだけで完了。[A-1]〜[A-5] を含む QC ループ全体が **Codex 側で自律完走**する。Claude は `done/<job-id>/progress.json` を受け取って後処理するのみ（本セクションのループ疑似コードは inline 専用）。

#### パラメータ

| パラメータ | 既定値 | 説明 |
|---|---|---|
| `max_iter` | `3` | FAIL 判定で再生成を打ち切り `blocked_gpt_image2_web` にするしきい値 |
| バッチサイズ | `10` | 1バッチあたりのページ数（並列実行単位） |
| バッチ間待機 | `5秒` | API レート制限対策 |
| 保存形式 | PNG原本 + JPEG製本版 | gpt-image-2 は b64_json で PNG を返す。QC後に `page_{NNN}.jpg` も作成し、EPUBにはJPEG版を使う |

`max_iter` の調整目安:
- 高精度が必要な場合: `3` のまま
- 処理速度優先の場合: `1` も可。ただし不合格ページを最終ページとして通さない（FAIL ページはすぐ `blocked_gpt_image2_web` になる）

#### ループフロー（疑似コード）

プロトタイプ `hybrid_loop.py` の `def main()` を仕様化したもの。

```
CSV を読み込み、全ページリストを取得する
# character_defs.json を1回だけロードしてキャッシュ（ページごとに再読み込みしない）
char_defs = load_json("manuscript/characters/character_defs.json")

for page in pages:
    # テキストページ判定（OCR・Vision-check・blocked処理全スキップ）
    if page の コマ別テキストJSON == []:
        画像生成をスキップ（テキストページは生成不要）
        PASS として記録 → 次ページへ

    # A路線: 生成 → OCR + Vision-check → 統合判定 ループ
    current_prompt = 元の画像生成プロンプト
    converged = False
    # ページに登場するキャラを抽出（char_defs キャッシュを渡す）
    page_chars = extract_page_chars(page.prompt, char_defs)

    for iter in range(1, max_iter + 1):
        # [A-1] 画像生成（gpt-image-2）— inline モード専用
        # codex-handoff モード時はこの疑似コード全体が Codex 側で完結するため省略
        画像を生成し pages/page_{NNN}_iter_{iter}.png に保存

        # [A-2] Blind-OCR（→ Step 5-QC 参照）
        # セリフなしページ（コマ別テキストJSON == []）は OCR スキップ（自動 PASS 扱い）
        ocr_verdict = blind_ocr_and_compare(pages/page_{NNN}_iter_{iter}.png, コマ別テキストJSON)

        # [A-3] Vision-check（→ Step 5-QC 参照）
        # 画像生成が発生した全ページを対象（セリフなしページも必ず実行）
        # キャラ名リストは「名前を先に提示した上で1人ずつ YES/NO を返す」設計（確証バイアス排除）
        vision_verdict, missing_chars = vision_check(pages/page_{NNN}_iter_{iter}.png, page_chars)

        # [A-4] 統合判定: OCR PASS かつ Vision-check PASS → ページ PASS
        if ocr_verdict == PASS and vision_verdict == PASS:
            pages/page_{NNN}_iter_{iter}.png を pages/page_{NNN}.png としてコピー
            converged = True
            progress.json を更新（このページ完了）
            break

        # [A-5] FAIL 時フィードバック注入（OCR 側・Vision-check 側を個別に追記）
        current_prompt = build_feedback_prompt(元のプロンプト, ocr_verdict, vision_verdict, missing_chars)
        # OCR FAIL → ◆【前回失敗・最重要】パネル別の不一致を追記
        # Vision-check FAIL → ◆【前回失敗・最重要】欠落キャラ名を全身イラストで描くよう追記

    # max_iter 超過時: blocked（該当ページを止める）
    if not converged:
        prompts/page_{NNN}_blocked_prompt.txt に最終プロンプトを保存
        blocked_reason = determine_blocked_reason(ocr_verdict, vision_verdict)
        # blocked_reason: "ocr_fail" / "vision_fail" / "both_fail"
        progress.json の blocked_pages[] に page_num を追加し blocked_reasons{page_num: blocked_reason} で記録
        このページを最終成果物にしない（pages/page_{NNN}.png を作らない）
        ログに [blocked] page {NNN}: gpt_image2_web blocked (reason=blocked_reason, missing=[...]) を出力

各バッチ完了後に progress.json を更新する
バッチ間は 5 秒待機する
```

#### 処理の流れ（詳細）

**1. ページごとに iter = 0 で開始**

CSV の全ページを 10 ページずつのバッチに分割し、各バッチ内は並列実行（`run_in_background: true`）する。

**2. テキストページ判定（空配列 → 自動 PASS）**

CSV の `コマ別テキストJSON` 列が空配列 `[]` のページはテキストページとみなす。
- 画像生成をスキップする（生成不要）
- OCR・Vision-check・blocked処理もすべてスキップする
- 自動的に PASS として `progress.json` に記録して次ページへ進む

**2a. character_defs.json のロードとキャッシュ**

ページループ開始前に `manuscript/characters/character_defs.json` を1回だけ読み込んでキャッシュする。
ページごとに再読み込みしない（I/O 削減）。
`extract_page_chars(prompt, char_defs)` にキャッシュ済み辞書を渡し、当該ページのキャラリストを取得する。

**3. 画像生成（プロンプト + フィードバック注入）**

各 iter の生成設定:
- `IMAGE_PROMPT`: iter=1 は CSV の `漫画作成のプロンプト`、iter=2以降はフィードバック注入済みプロンプト
- `OUTPUT_FOLDER`: `{vol_dir}/pages`（分冊時）または `panels/pages`（単巻時）
- `SIZE`: `"1024x1536"`（2:3縦長）
- `FILE_PREFIX`: `page_{ページ番号3桁ゼロ埋め}_iter_{iter}` （例: `page_039_iter_1`）
- **保存形式**: 生成直後はPNG（`.png`）で保存し、QC PASS後に同寸法JPEG（`.jpg`）も作成する。EPUB製本にはJPEG版を使用する
- **生成経路**: ChatGPT Images 2.0（Codex/ChatGPT側の画像生成。API不使用）
- **参照画像**: プロンプト内の `添付の([^\s、,]+?\.png)` から抽出したキャラクターリファレンス PNG を、ChatGPT/Codexの画像生成に参照画像として添付する

**codex-handoff モード時の Step 5-A（バンドル投入）:**

1. ジョブ ID 生成: `{book_id}_vol{N}_{YYYYMMDD_HHMMSS}`（Step 5 と Step 6 を同一 job-id で扱う）
2. `.company/codex/queue/<job-id>/` を作成
3. `manifest.json` を `task_type: "manga_bundle"` 形式で生成:
   - `items[]` に **全本文ページ** (`type: "page"`) と **表紙** (`type: "cover"`) を含める
   - `qc_policy: {max_iter: 3, ocr_model: "gpt-4o", vision_check: true}`
   - `cover_config: {cover_ref_character_id: "<主人公キャラID>", size: "1024x1536"}`
4. `manuscript/characters/` の PNG を `queue/<job-id>/characters/` にコピー
5. `panels/comicle_output.csv` を `queue/<job-id>/csv/comicle_output.csv` にコピー
6. `.company/codex/_spec/gen_manga_bundle.py` を `queue/<job-id>/gen_manga_bundle.py` にコピー
7. `.company/codex/_template.md` を流用して `queue/<job-id>/TASK.md` を生成（job-id / book_id / vol を埋め込む）
8. ユーザーに以下を提示:
   ```
   queue/<job-id>/ を配置しました。別ターミナルで以下を実行してください:
     cd .company/codex/queue/<job-id>
     python gen_manga_bundle.py
   完了したら「Codex 完了しました」と教えてください。
   ```

**codex-handoff モード時の Step 5-C（done 受取）:**

> 注: fire-and-forget 方式のため、queue 投入から done 受取までの間 Claude 側の能動操作は不要。
> ユーザーから「Codex 完了しました」通知を受けた時点で以下を実行する。

ユーザーから「Codex 完了しました」の通知を受けたら:

1. `.company/codex/done/<job-id>/progress.json` を読み込む
2. `status` フィールドを確認:
   - `"success"`: 全ページ PASS
   - `"partial"`: 一部失敗あり（failed 項目を確認）
   - `"failed"`: 大多数失敗（ユーザーに報告して再投入判断）
3. `done/<job-id>/pages/page_{NNN}.png` を書籍側 `panels/pages/page_{NNN}.png` にコピーし、同寸法JPEG版 `panels/pages/page_{NNN}.jpg` を作成する
4. `done/<job-id>/cover.png` を `KDP出版用/cover.png` にコピーし、同寸法の `KDP出版用/cover.jpg` も作成
5. `blocked_pages[]` が空でない場合、書籍側 `progress.json` に転記し、該当ページを再生成して解消するまで Step 7 に進まない
6. 書籍側 `progress.json` の Step 5 / Step 6 を `done` に更新
7. `done/<job-id>/` を `.company/codex/archive/<job-id>/` に移動
8. Step 7（EPUB 化）へ進む

なお、codex-handoff モードでは QC ループ（Blind-OCR・Vision-check・blocked判定）はすべて Codex 側で実行され、結果が `progress.json` の `blocked_pages` に反映される。

ChatGPT Images 2.0で生成する:

1. プロンプトから参照画像ファイル名を抽出する
2. `manuscript/characters/*.png` の該当画像を参照画像として添付する
3. `IMAGE_PROMPT` をそのまま投入し、2:3縦長で生成する
4. 生成PNGを `pages/page_{NNN:03d}_iter_{iter}.png` に保存する
5. APIキー、SDK、`client.images.*` は使わない

**4. Blind-OCR 判定（→ Step 5-QC 参照）**

生成した `pages/page_{NNN}_iter_{iter}.png` を `### Step 5-QC` の仕様に従って OCR する。
OCR はAPIではなく、ChatGPT/Codex上の視覚確認またはローカルOCRで実行し、期待テキストは一切渡さない。
セリフなしページ（`コマ別テキストJSON == []`）は OCR をスキップし、自動 PASS 扱いとする。

**5. Vision-check 判定（→ Step 5-QC 参照）**

`### Step 5-QC` の「Vision-check」仕様に従い、`pages/page_{NNN}_iter_{iter}.png` に対して
ChatGPT/Codex上の視覚確認でキャラ存在チェックを実行する。
- 画像生成が発生したすべてのページ（セリフあり・セリフなし問わず）を対象とする
- セリフなしページも必ず Vision-check を実行する（OCR オートPASS の穴を塞ぐ）
- `extract_page_chars(prompt, char_defs)` で当該ページの登場キャラを絞り込み、そのキャラのみをチェックする
- テキストページ（画像生成スキップ済み）はスキップする

**6. 統合判定（OCR + Vision-check）**

`### Step 5-QC` の「OCR と Vision-check の統合判定」テーブルに従い判定する。

| ページ種別 | OCR 判定 | Vision-check 判定 | ページ確定条件 |
|---|---|---|---|
| セリフありページ | 実行 | 実行 | 両方 PASS のみ確定 |
| セリフなしページ（画像生成あり） | スキップ（自動 PASS） | 実行 | Vision-check PASS で確定 |
| テキストページ（画像生成なし） | スキップ | スキップ | 自動確定 |

両方 PASS → `pages/page_{NNN}_iter_{iter}.png` を `pages/page_{NNN}.png` としてコピーし、
このページを完了として次ページへ進む。

**7. FAIL 時: フィードバック構築 → iter += 1 → 3 に戻る**

`### Step 5-QC` の「FAIL 時のフィードバック注入（拡張版）」に従い、OCR FAIL 分と
Vision-check FAIL 分をそれぞれ個別のセクションとしてプロンプト末尾に追記する。
- OCR FAIL → `◆【前回失敗・最重要】` パネル別不一致エントリを追記
- Vision-check FAIL → `◆【前回失敗・最重要】` 欠落キャラ名リストを追記
- 両方 FAIL の場合は両セクションを併記する
次の iter の画像生成にこのプロンプトを使用する。

**8. max_iter 超過 → blocked**

`max_iter` 回すべて FAIL した場合（OCR FAIL・Vision-check FAIL どちらの原因でも同様）、
該当ページは `blocked_gpt_image2_web` として止める。
最終プロンプト・失敗理由・参照画像を保存し、最後の iter 画像を最終成果物として採用しない
（`pages/page_{NNN}.png` を作らない）。
`progress.json` の `blocked_pages[]` に当該ページ番号を追加し、
`blocked_reasons{page_num}` に `"ocr_fail"` / `"vision_fail"` / `"both_fail"` を記録する（→ 進捗管理セクション参照）。
ログに `[blocked] page {NNN}: gpt_image2_web blocked (reason=..., missing=[...])` を出力する。

#### 成果物ファイル命名

| ファイル名パターン | 生成タイミング | EPUB 向け扱い |
|---|---|---|
| `pages/page_{NNN}_iter_{N}.png` | 各 iter の生成画像 | 監査用。PASS した iter の画像のみ `page_{NNN}.png` にコピーされる |
| `pages/page_{NNN}.png` | PASS したページの最終原本画像 | 監査・再変換用の原本として保持する |
| `prompts/page_{NNN}_blocked_prompt.txt` | max_iter 超過時 | 再生成用。EPUBには入れない |
| `pages/page_{NNN}.jpg` | Step 5 のEPUB製本用画像（`page_{NNN}.png` から同寸法で変換） | Step 7 EPUB 製本が直接参照する |

> **EPUB製本（Step 7）との整合**: Step 7 は `pages/page_{NNN}.jpg` を収集する。JPEG版がない場合のみ、例外的にPNGからJPEGを生成してから製本する。
> この運用により EPUB 容量を抑えやすくなる。
> `blocked_gpt_image2_web` ページが残っている場合は Step 7 に進まない。

#### 進捗管理

各バッチ完了後に `progress.json` を更新する。

```json
"5_images": {
  "status": "done",
  "completed": 100,
  "total": 100,
  "failed": [],
  "blocked_pages": [],
  "blocked_reasons": {},
  "vision_check_failed_pages": [2, 17],
  "vision_check_pages": 95
}
```

- `failed` 配列: Web生成またはQCで最終的に処理不能になったページを記録する
- `blocked_pages`: `blocked_gpt_image2_web` として止めたページ番号リスト
- `blocked_reasons`: blockedページごとの理由。値は `"ocr_fail"` / `"vision_fail"` / `"both_fail"` / `"web_unavailable"` など
- `vision_check_failed_pages`: Vision-check で1回以上 FAIL したページ番号リスト。最終的に PASS したページも記録する（監査用）
- `vision_check_pages`: Vision-check を実施したページ数の集計
- blocked時は `progress.json` の当該ページに `"status": "blocked_gpt_image2_web", "blocked_reason": "{reason}"` を追記する
- ログに `[blocked] page {NNN}: gpt_image2_web blocked (reason={reason}, missing=[キャラ名])` を出力する

#### コスト試算

**単純生成コスト: $21.00/冊**

| 項目 | 単価目安 | 冊あたり |
|---|---|---|
| 画像生成（gpt-image-2）× 100P | $0.21/枚（1024x1536 high） | $21.00 |
| 単純生成合計 | — | **$21.00/冊** |

**ハイブリッドQC追加コスト: +$3.15〜$3.75/冊**

| 追加項目 | 想定 | コスト目安 |
|---|---|---|
| Blind-OCR（gpt-4o）× 平均 1.5 iter/P × 100P | 150コール | +$1.50 |
| **Vision-check（gpt-4o）× 平均 1.2 iter/P × 100P** | **120コール** | **+$0.60〜$1.20** |
| FAIL ページの追加生成（iter 2〜3 の再生成） | 難ページ約 20%、平均 2 iter | +$0.84 |
| 追加合計 | — | **+$2.94〜$3.54/冊** |

**合計: $24.15〜$24.75/冊（ハイブリッドQC込み）**（中央値: **$24.45/冊**）

※ 要件定義書のコスト試算（$34.89/冊）はバッファ込みの上限値。上表は内訳積み上げの標準見積もり。
※ Vision-check FAIL による再生成 iter が追加で発生した場合は、Vision-check コールが上記より増加する。

**max_iter 変更時のコスト試算:**

| max_iter | 期待 OCR コール数 | 期待 Vision-check コール数 | 追加コスト目安 |
|---|---|---|---|
| 1 | 100（1回のみ） | 100（1回のみ） | +$1.60〜$2.20（blocked多め） |
| 2 | 120〜140 | 110〜130 | +$2.60〜$3.20 |
| **3（既定）** | **130〜150** | **115〜125** | **+$3.15〜$3.75** |
| 4 | 150〜170 | 120〜135 | +$3.80〜$4.40（blocked率低下） |

> **注**: `max_iter=3` の追加コスト `+$3.15〜$3.75` は内訳積み上げ値。
> レート変動・iter 超過・OCR/Vision-check リトライ等のバッファを加味した安全側見積もりは工程1のコスト試算テーブル（`$34.89/冊`）を参照。

**blocked発動率の想定**: 全ページの約 5%（難ページ：長セリフ・複数キャラ同時発話・小さいコマ等）。
iter 3 回の反復で約 95% のページは A路線で収束する見込み（プロトタイプ実測に基づく推定）。

#### 維持される Step 4 と Step 6 の仕様

**Step 4 との接続（上流）:**
- Step 4 で生成した CSV（`panels/comicle_output.csv`）の `コマ別テキストJSON` 列が
  本ループの Blind-OCR 比較の期待テキスト源になる
- 使用するコマ割りテンプレは Step 4 の CSV `使用するコマ割りテンプレ` 列から取得する（7種）
- キャラクターリファレンス画像（`character_defs.json`）は Step 3 の成果物を引き続き使用する

**Step 6 との接続（下流）:**
- 本ステップ完了後、全ページが `pages/page_{NNN}.png`（原本）と `pages/page_{NNN}.jpg`（EPUB用）として揃っており、`blocked_pages` が空であること
- Step 6（カバー画像生成）はこのファイル群を参照しないため影響なし
- Step 7（EPUB製本）は `pages/page_{NNN}.jpg` を収集するため、命名規則の一貫性が保証されていれば修正不要

---

### Step 5-QC: Blind-OCR + Vision-check 判定モジュール

Step 5 の画像生成ループ内で使用する OCR 品質判定の仕様。
工程5（Step 5 ループ全面改修）でこのサブセクションを参照してループを組む。

#### 設計原則: Confirmation Bias 排除（最重要）

**OCR プロンプトに期待テキストを絶対に含めない。**

反面教師となった実装（`vlm_dialogue_check.py`）では、期待テキストをプロンプト内に
`【期待されるセリフ・ナレーション】` として提示していた。この方式では OCR モデルが
期待値を見てから画像を解釈するため、誤字・脱字があっても「合っている」と判定する
偽陽性（confirmation bias）が発生した。

正しい設計:
- OCR は純粋な「画像 → テキスト抽出」タスクとして実行する
- OCR モデルには画像のみを渡し、「何が書かれているか読み取れ」とだけ指示する
- 期待テキストとの照合は **OCR 完了後にプログラム側（Python）で** 行う
- この分離により、OCR モデルは期待値の影響を受けず画像の実態を報告する

#### OCR 対象と対象外

**対象（必ず読み取る）:**
- 吹き出し（楕円・雲形）内の文字 → `type="dialogue"`
- ナレーションボックス（四角枠・角丸枠）内の文字 → `type="narration"`

上記は CSV の `コマ別テキストJSON` で `type="dialogue"` / `type="narration"` として
定義されたテキストに対応する。

**対象外（無視する）:**
- オノマトペ・擬音（ぱぁっ / ビクッ / ドンッ 等）
- 背景の看板・ポスター・標識
- 小物の UI・ラベル（スマホ画面・PC画面・本の表紙・商品パッケージ等）
- キャラクターの服のロゴ・ブランド表記

対象外はすべて CSV の `コマ別テキストJSON` に含めていないため、
OCR が対象外を拾っても比較対象が存在せず無視される。

**OCR の粒度: 画像全体を一括で渡す。**
コマ領域ごとにクロップして個別 OCR するのではなく、ページ全体画像を1回の視覚確認で処理する。
OCR モデルはページ全体から各吹き出しを自動検出し、`panel_id` と `type` を推定する。
（コマ領域の切り出し機能は現在未使用。将来の手動レビューツール用に保持。）

#### OCR プロンプトテンプレート

実行経路: ChatGPT/Codex上の視覚確認またはローカルOCR（API不使用）
出力形式: JSONのみ

```text
添付のマンガ画像を見て、下記の要素を画像に描かれている通り正確に読み取ってください。
推測や補完は一切せず、画像に実際に見える文字列だけを返してください。
読めない崩し字や意味不明な文字列も、見える通りに書いてください（勝手に正しい日本語に補正しない）。

対象:
- 吹き出し（楕円・雲形）内の文字 -> type="dialogue"
- ナレーションボックス（四角枠・角丸枠）内の文字 -> type="narration"

対象外（読み取らない）:
- オノマトペ・擬音
- 背景の看板・ポスター・標識
- 小物のUI・ラベル（スマホ画面・PC画面・本の表紙・商品パッケージ等）
- 服のロゴ・ブランド表記

出力形式: JSONのみ。説明文・マークダウン禁止。読み取れたテキストは改行なしで1行に連結。
{
  "bubbles": [
    {"panel_id": int, "type": "dialogue"|"narration", "detected_text": str}
  ]
}
```

**重要**: このプロンプトには期待テキスト（CSV の `text` フィールドの値）を一切含めない。

#### 比較ロジック（決定論的）

OCR 完了後、以下の手順でプログラム側（Python）が比較を行う。

**ステップ1: テキスト正規化（両辺に適用）**
```python
import unicodedata, re

def normalize_text(s: str) -> str:
    if s is None:
        return ""
    s = unicodedata.normalize("NFKC", s)  # 全角/半角統一（例: ｢→「、ｶﾅ→カナ）
    s = re.sub(r"\s+", "", s)              # 空白・改行・タブをすべて除去
    return s
```

NFKC 正規化により全角/半角の揺れを吸収する。空白・改行除去により縦書きレンダリングの
改行差異を吸収する。

**ステップ2: キーによる突き合わせ**
- 突き合わせキー: `(panel_id, type)` のペア
- OCR 結果の `bubbles` 配列を `{(panel_id, type): [detected_text, ...]}` の辞書に変換する
- CSV の `コマ別テキストJSON` 各エントリについて、同じキーの OCR バブルを検索する
- 1コマに同 type が複数ある場合（例: 2人のセリフ）は、未使用の候補の中から最初に
  正規化一致するものを採用する（used セットで重複消費を防ぐ）
- **fuzzy matching（編集距離・部分一致）は禁止。完全一致のみ有効とする。**

**ステップ3: 判定**
- 各エントリで `normalize_text(detected) == normalize_text(expected)` を評価する
- 全エントリが一致 → `match=True`
- 1エントリでも不一致 → `match=False`

#### PASS/FAIL 判定条件

**ページ単位の判定:**
- CSV の `コマ別テキストJSON` の全エントリが `match=True` → ページ **PASS**
- 1エントリでも `match=False` → ページ **FAIL** → 再生成トリガー

**テキストページの扱い:**
- CSV の `コマ別テキストJSON` が空配列 `[]` のページはテキストページとみなす
- テキストページは OCR をスキップし、自動的に **PASS** 扱いとする
- 画像生成自体もスキップ済みのため、判定処理は不要

**FAIL 時のフィードバック注入:**
FAIL の場合、次の iter の生成プロンプト末尾に以下のセクションを追記する:

```
◆【前回失敗・最重要】前回生成では以下が正しく描画されませんでした。今回は一字一句正確に描くこと:
- パネル{panel_id}の{種別}: 正「{expected}」 ⇔ 前回誤「{detected[:40]}」
```

- `種別` は `type=="dialogue"` なら「セリフ」、`type=="narration"` なら「ナレーション」
- `detected[:40]` は検出テキストの先頭40文字（長文の切り詰め）
- FAIL したエントリのみ列挙する（PASS 済みのエントリは含めない）

#### エラーハンドリング

**OCR API エラー・空レスポンス時:**
- OCR 呼び出しは最大 **2回リトライ**（合計3回試行）する
- リトライ間隔: 1秒
- 3回すべて失敗した場合は `{"bubbles": []}` を返す（空バブル扱い）
- 空バブルは比較時に「検出テキストなし」として全エントリが FAIL になる
- つまり OCR 失敗は自動的に FAIL 扱いとなり、次の iter または `blocked_gpt_image2_web` に進む

**JSON パースエラー時:**
- OCR レスポンスが JSON として解析できない場合、部分修復を試みる
  （正規表現で `"bubbles": [...]` 部分を抽出して再パース）
- 修復も失敗した場合は `{"bubbles": []}` を返す（空バブル = FAIL 扱い）

**ログ出力:**
- OCR リトライ発生時は `[ocr] WARN: OCR failed after retries: {error}` をログ出力する
- 各 iter の判定結果（PASS/FAIL、FAIL したパネル番号と type）をログ出力して
  どのコマが何回 FAIL したかを追跡可能にする
  - 例: `[iter 2] FAIL: panel=2 type=dialogue expected='佐藤さん...' detected='佐藤ざん...'`
- progress.json の `failed` 配列には iter 超過して FAIL したページ番号のみ記録する
  （iter 内で最終的に PASS したページは failed に記録しない）

#### OCR と Vision-check の統合判定

**ページ単位の最終判定:**

| ページ種別 | OCR | Vision-check | ページ判定 |
|---|---|---|---|
| セリフありページ | 実行 | 実行 | どちらか一方でも FAIL → ページ FAIL |
| セリフなしページ（画像生成あり） | スキップ（期待テキスト空 = 自動 PASS） | 実行 | Vision-check FAIL → ページ FAIL |
| テキストページ（画像生成なし） | スキップ | スキップ | 自動 PASS |

- OCR と Vision-check は独立して実行する（並列 or 直後、どちらでも可）
- どちらか一方でも FAIL の場合 → ページ FAIL → 再生成トリガー
- 両方 PASS の場合のみ → ページ確定（`converged = True`）
- セリフなしページは OCR 実質スキップ（期待テキスト空のため全エントリ一致扱い）、Vision-check は必ず実行する

**FAIL 時のフィードバック注入（拡張版）:**

OCR FAIL 時は既存フォーマットそのまま:
```
◆【前回失敗・最重要】前回生成では以下が正しく描画されませんでした。今回は一字一句正確に描くこと:
- パネル{panel_id}の{種別}: 正「{expected}」 ⇔ 前回誤「{detected[:40]}」
```

Vision-check FAIL 時は以下を追記:
```
◆【前回失敗・最重要】前回生成では以下のキャラクターが描画されていませんでした。今回は必ず全身イラストで描いてください: {欠落キャラ名リスト}
```

両方 FAIL の場合は両セクションを併記する。

---

#### Vision-check: キャラ存在検証の設計原則

**目的**: 画像生成ループ内でキャラ欠落バグ（例: page_002 山田課長省略事象）を自動検出し、
再生成トリガーをかけることで全キャラが正しく描画された画像を確定する。

**confirmation bias 排除方針**:
- OCR の反面教師（期待テキストをプロンプトに含める設計）とは異なり、
  Vision-check は「このキャラクターが存在するか」を1人ずつ YES/NO で問う。
- 「全員が存在するか」をまとめて問うと、モデルが期待値に引っ張られて過剰に YES を返す
  確証バイアスが発生する恐れがある。キャラごとに個別質問することで判定精度を高める。
- システムプロンプトで「テキスト枠・名前ラベルのみの場合は NO とする」と明示し、
  「文字でキャラ名が書かれている」と「イラストが描かれている」の混同を防ぐ。

#### 対象ページ

**Vision-check を実行するページ:**
- `コマ別テキストJSON` が空配列 `[]` かつ画像生成が実行されたページ（セリフなしページ。例: 登場人物紹介ページ）
- `コマ別テキストJSON` に1件以上のエントリがあるページ（セリフありページ）

つまり、**画像生成が発生したすべてのページ**が Vision-check の対象となる。

**Vision-check をスキップするページ:**
- テキストページ（`コマ別テキストJSON` が `[]` かつ Step 5 で画像生成自体をスキップ済みのページ）
  - これらは画像ファイルが存在しないため Vision-check の対象外とする

#### キャラ名抽出ロジック

Vision-check で確認対象とするキャラ名は、当該ページのプロンプトに登場するキャラのみに絞り込む。
全キャラを毎ページチェックすると「このページには登場しないキャラ」への質問が多発し、
誤 FAIL の原因となるため、プロンプト内の記載で絞り込む設計とする。

**抽出元1: `character_defs.json`（Step 3 成果物、キャラ名マスター）**

```json
[
  {"id": "misaki", "name": "ミサキ", "appearance": "30代女性、ボブヘア、ボーダーシャツ"},
  {"id": "kenta",  "name": "ケンタ",  "appearance": "30代男性、グレーTシャツ"},
  ...
]
```

`character_defs.json` から全キャラの `name` と `appearance` を読み込み、
name → appearance のマッピング辞書を構築する。

**抽出元2: 当該ページの CSVプロンプト（`漫画作成のプロンプト` 列）の `◆【絶対最優先】キャラクター外見:` ブロック**

プロンプト内に登場するキャラ名を正規表現で抽出し、`character_defs.json` のマスターと突き合わせて
appearance 付きのキャラリストを生成する。

```python
import re

def extract_page_chars(prompt: str, char_defs: list[dict]) -> list[dict]:
    """
    プロンプトの「◆【絶対最優先】キャラクター外見:」ブロックから
    登場キャラ名を抽出し、character_defs.json の外見情報と結合して返す。

    Returns:
        [{"name": "ミサキ", "appearance": "30代女性、ボブヘア、ボーダーシャツ"}, ...]
    """
    # character_defs.json から name -> appearance マッピングを構築
    char_map = {c["name"]: c.get("appearance", "") for c in char_defs}

    # プロンプト内の「◆【絶対最優先】キャラクター外見:」ブロックを抽出
    block_match = re.search(
        r"◆【絶対最優先】キャラクター外見:\s*(.+?)(?=\n◆|\Z)",
        prompt,
        re.DOTALL,
    )
    if not block_match:
        return []

    block_text = block_match.group(1)

    # 「添付の〇〇.png」または「〇〇は添付の」パターンからキャラ名を動的抽出
    found_names = re.findall(r"添付の(.+?)\.png", block_text)
    # スペース除去・重複排除
    found_names = list(dict.fromkeys(name.strip() for name in found_names))

    result = []
    for name in found_names:
        appearance = char_map.get(name, "")
        result.append({"name": name, "appearance": appearance})
    return result
```

プロンプト内で言及されているキャラのみを Vision-check 対象とする（登場しないキャラまでチェックすると誤検出）。

#### Vision-check プロンプトテンプレート

実行経路: ChatGPT/Codex上の視覚確認（API不使用）
出力形式: JSONのみ

**システムプロンプト:**
```
あなたは画像品質チェッカーです。与えられたマンガ画像を分析し、
指定されたキャラクターが全身イラストとして描かれているかを1人ずつ YES または NO で判定してください。
テキスト枠・名前ラベルのみでキャラクターのイラスト本体が存在しない場合は NO としてください。
イラストが実際に画像内に描かれているかを画像の内容から判断してください。必ず JSON で返してください。
```

**ユーザープロンプト（動的生成）:**
```
以下のマンガ画像に、キャラクター{N}人 [{name_list}] がそれぞれ全身イラストとして描かれているか、
1人ずつ YES/NO で答えてください。テキスト枠のみ（名前タグのみでイラストなし）は NO とします。

出力形式（JSONのみ。説明文禁止）:
{{"vision_checks": [{{"char_name": "ミサキ", "result": "YES", "reason": "..."}}]}}
```

**確認手順:**

1. チェック対象のPNGを表示する
2. `page_chars` から確認対象キャラ名と外見補足を抽出する
3. 上記のシステムプロンプトとユーザープロンプトに沿って、ChatGPT/Codex上で視覚確認する
4. 下記スキーマのJSONとして結果を記録する
5. APIキー、SDK、外部API呼び出しは使わない

**レスポンス JSON スキーマ:**
```json
{
  "vision_checks": [
    {"char_name": "ミサキ", "result": "YES", "reason": "1段目に全身イラストあり"},
    {"char_name": "山田課長", "result": "NO", "reason": "テキスト枠のみ、イラストなし"}
  ]
}
```

#### 判定ロジック

```python
def vision_check_pass(vision_result: dict) -> tuple[bool, list[str]]:
    """
    Returns:
        (is_pass, missing_chars)
        - is_pass: True = Vision-check PASS、False = Vision-check FAIL
        - missing_chars: FAIL 時の欠落キャラ名リスト（PASS 時は空リスト）
    """
    checks = vision_result.get("vision_checks", [])
    missing = [c["char_name"] for c in checks if c.get("result") != "YES"]
    return (len(missing) == 0), missing
```

- 全キャラが `result: "YES"` → Vision-check **PASS**
- 1人でも `result: "NO"` → Vision-check **FAIL** → 再生成トリガー
- `vision_checks` が空配列（パースエラー等） → 全員 NO 扱い → **FAIL**

#### エラーハンドリング

**Vision-check API 失敗時:**
- Vision-check 呼び出しは最大 **2回リトライ**（合計3回試行）する
- リトライ間隔: 1秒
- 3回すべて失敗した場合は FAIL 扱いとする（安全側に倒す）
  - API 不安定による誤 FAIL のリスクより、キャラ欠落の見逃しリスクを優先して回避する

**JSON パースエラー時:**
- レスポンスが JSON として解析できない場合、部分修復を試みる
  （正規表現で `"vision_checks": [...]` 部分を抽出して再パース）
- 修復も失敗した場合は `{"vision_checks": []}` を返す（空配列 = 全員 NO 扱い = FAIL）

**ログ出力:**
- リトライ発生時: `[vision] WARN: Vision-check failed after retries: {error}`
- FAIL 検出時: `[vision] FAIL: page={NNN} missing=[山田課長, ケンタ]`
- 各 iter の判定結果: `[vision] iter_{N} char={name} result={YES/NO} reason={reason}`

---

### Step 6: 表紙作成

マンガ版の書籍表紙を生成する。

> **モード別フロー概要**
> - `inline` モード: 6-A プロンプト構築 → 6-B-inline 直接生成 → 6-C ユーザー確認
> - `codex-handoff` モード: Step 6 表紙は Step 5-A のバンドルに `type: "cover"` の item として統合済みのため、独立した Step 6-A / 6-B / 6-C の操作は不要。Step 5-C（done 受取）の中で表紙 PNG も一括して受け取る。

#### 6-A: 表紙プロンプト構築（共通）

以下の手順でプロンプトを組み立てる（モード共通）。

#### 表紙プロンプトの構成

既存の `表紙プロンプト.md` の5ステップ構造をベースに、マンガ用に適応する:

```yaml
request_type: generate_hyper_detailed_magazine_cover_with_fixed_aspect_ratio
title: "マンガでわかる {元タイトル}"
subtitle: "{元サブタイトル}"
author: "{著者名}"

description: >
  添付された原稿ドキュメントファイルを分析して抽出したテキスト要素を使用して、
  圧倒的な情報量と高いデザイン密度を備えたプロ仕様の「マンガ書籍カバー」を生成する。

design_taste: >
  マンガ・コミック風の書籍カバーデザイン。
  {Step 1で選択したジャンルの作画設定の色調・演出を反映}
  キャラクターを全面に配置し、マンガらしい躍動感を演出。
  SNSでバズるサムネイルのような高コントラスト・高彩度の配色で、
  Amazonの検索結果一覧の小さなサムネイルでも一瞬で目を引くデザインにする。

buzz_elements: >
  - タイトルは画面幅いっぱいの極太文字で、サムネイルサイズでも読めること
  - 数字や強いベネフィットを入れた帯風キャッチコピーを1本入れる（例:「たった1日10分」「9割の人が知らない」「読むだけで変わる」）
  - キャラクターは感情がひと目で伝わる大きな表情（驚き・笑顔・決意）にする
  - 吹き出しやバッジ風の装飾で「初心者OK」「マンガでサクッと」など読者メリットを短く入れる
  - 情報はタイトル/キャッチコピー/装飾の3階層に整理し、詰め込みすぎてごちゃつかせない

character: >
  {character_defs.jsonの主要キャラクター2-3名の外見設定}
  キャラクター同士の関係性が伝わるポーズ・配置。

processing_steps:
  - step 1: 原稿分析とテキスト要素抽出
  - step 2: デザインムードと構図の決定
  - step 3: キャラクター配置と背景の生成（2:3アスペクト比）
  - step 4: テキストと装飾要素のレイアウト
  - step 5: キャラクター・背景とテキスト・装飾の統合
```

#### 6-B: 生成実行（モード別）

**ChatGPT Images 2.0直生成モード（標準）:**

APIは使わない。主人公キャラのリファレンス画像をChatGPT/Codex側の画像生成に添付し、`COVER_PROMPT` を投入して生成する。

1. `COVER_PROMPT_TEXT` に含まれる `添付の*.png`、または Step 3 で生成済みの `chara_*.png` を参照画像にする
2. ChatGPT Images 2.0で 2:3 縦長の表紙を生成する
3. 生成PNGを `KDP出版用/cover.png` に保存する
4. 同寸法の `KDP出版用/cover.jpg` をKDP申請用に作成する
5. `OPENAI_API_KEY`、OpenAI SDK、`openai-image-gen`、`client.images.edit` は使用禁止

- サイズ: `size="1024x1536"`（2:3縦長形式）
- 品質: `quality="high"`
- 保存先: `KDP出版用/cover.png`（マスター）と `KDP出版用/cover.jpg`（KDP申請用JPEG版）

**codex-handoff モード時（Step 6 全体）:**

Step 6-A のバンドルに表紙 item（`type: "cover"`）を Step 5-A で一括投入済みのため、Step 6-B-codex / 6-C-codex の独立した操作は不要。
`done/<job-id>/cover.png` は Step 5-C（done 受取）の中で `KDP出版用/cover.png` にコピーされる。受け取り後、同寸法の `KDP出版用/cover.jpg` も必ず作成する。

もし Step 6 単独で再生成が必要な場合は、新 job-id で `manifest.json` の `items[]` に `type: "cover"` のみ 1 件を含めて投入する（--only-step 6 相当の動作）。

#### ユーザー確認
- 表紙画像をReadツールで表示して確認を得る
- サムネイル縮小表示（幅100px相当）を想定してタイトル・帯風キャッチコピーが判読できるかを確認し、読めなければ文字を大きくして再生成する
- 不満があればプロンプトを修正して再生成する

---

### Step 7: 製本（EPUB化）

固定レイアウトEPUB3をPythonで直接構築する。
**Pandocでは固定レイアウトEPUBを生成できないため、`zipfile` モジュールを使用する。**

#### EPUB構造

```
mimetype                          (非圧縮)
META-INF/
  └── container.xml
OEBPS/
  ├── content.opf                 (パッケージメタデータ)
  ├── nav.xhtml                   (ナビゲーション)
  ├── style.css                   (スタイルシート)
  ├── fonts/
  │   ├── NotoSansJP-Regular.otf  (日本語ゴシック・埋め込み)
  │   └── NotoSansJP-Bold.otf
  ├── images/
  │   ├── cover.png
  │   ├── cover.jpg
  │   ├── page_001.png
  │   ├── page_002.png
  │   └── ...
  └── text/
      ├── cover.xhtml
      ├── page_001.xhtml          (画像ページ or テキストページ)
      ├── page_002.xhtml
      └── ...
```

#### テキストページの処理

CSVでテンプレが「テキストページ」のページは、画像ではなくHTMLテキストとしてEPUBに含める。
目次・あらすじ・コラム・著者紹介・奥付等がこれに該当する。テキストページ用CSSで読みやすくレンダリングする。

**改ページルール（必須）**: 各テキストページは表示行数が**最大20行**に収まるよう要素単位（h2/h3/p/subtitle）で折り返し行数を推定し、20行を超える場合は新しいXHTMLファイル（`page_NNN.xhtml`, `page_NNNb.xhtml`, `page_NNNc.xhtml` ...）に分割する。見出し（h2/h3）が末尾孤立しないよう、次の本文も同ページに入らない場合は見出しごと次ページへ送る orphan 回避を実装する。viewport 1024×1536 + 1.5倍フォントの条件では、p=42pxで1行63px、利用可能高さ約1444pxで20行≈1260pxとなり安全に収まる。

**改ページ実装例**: `C:\tmp\repaginate_vol1.py` を参照（`visual_lines()` で要素別の行数推定、`paginate()` で20行バジェットの貪欲パッキング）。

#### CTA固定ページ（後付け）

著者紹介ページの直後・奥付ページの直前に、全巻共通の固定CTA画像を spine に挿入する。

- **アセット**: `.claude/skills/ebook-to-manga/assets/cta.png`（1024×1536 PNG、全巻共通固定）
- **spine ID**: `page_cta`
- **挿入位置**: `... → page_NNN（著者紹介） → page_cta → page_NNN+1（奥付） → ...`
- **xhtml 生成**: 通常の画像ページと同じ `<div class="page"><img src="../images/page_cta.png" alt="ページ CTA"/></div>`
- **manifest 登録**: `<item id="page_cta" .../>` と `<item id="page_cta-img" href="images/page_cta.png" .../>` の2エントリ

```python
# CTA固定ページの挿入（著者紹介の直後・奥付の直前）
SKILL_DIR = os.path.expanduser("~/.claude/skills/ebook-to-manga")  # または相対パスでスキル位置を解決
CTA_IMAGE = os.path.join(SKILL_DIR, "assets", "cta.png")

# spine 構築時に著者紹介→CTA→奥付の順で追加
# spine.append(("page_NNN_author", "text"))   # 著者紹介
spine.append(("page_cta", "image_cta"))       # CTA固定
# spine.append(("page_NNN_colophon", "text")) # 奥付

# manifest 登録
manifest_items.append('    <item id="page_cta" href="text/page_cta.xhtml" media-type="application/xhtml+xml"/>')
manifest_items.append('    <item id="page_cta-img" href="images/page_cta.png" media-type="image/png"/>')

# EPUB書き込み
with open(CTA_IMAGE, "rb") as f:
    cta_data = f.read()
epub.writestr("OEBPS/images/page_cta.png", cta_data, compress_type=zipfile.ZIP_DEFLATED)
epub.writestr("OEBPS/text/page_cta.xhtml", make_image_xhtml("page_cta", "CTA"), compress_type=zipfile.ZIP_DEFLATED)
```

> **差し替えはアセットを更新するだけ**: CTAデザインを変更したい場合は `.claude/skills/ebook-to-manga/assets/cta.png` を新しい1024×1536 PNGで上書きする。次回以降のEPUBビルドで全巻に自動反映される。

#### フォント埋め込み（必須）

**端末（特にKindle）にインストールされたCJKフォントは中国語字形にフォールバックすることがあるため、
日本語ゴシックフォント（Noto Sans JP）を必ずEPUB内に埋め込むこと。**

- フォント取得元: `https://github.com/notofonts/noto-cjk/raw/main/Sans/SubsetOTF/JP/NotoSansJP-Regular.otf`（Bold同様）
- ライセンス: SIL Open Font License（再配布可・商用利用可・KDP出版可）
- EPUB内パス: `OEBPS/fonts/NotoSansJP-{Regular,Bold}.otf`
- ZIP格納時は `ZIP_STORED`（既圧縮のため再圧縮しない）
- `style.css` の `@font-face` で参照、`font-family` の先頭に `"Noto Sans JP"` を指定
- `content.opf` の manifest に `media-type="application/vnd.ms-opentype"` で登録

#### テキストページCSS（標準サイズ）

テキストページのフォントサイズは「画像ページの読みやすさ」と揃えるため以下を標準とする
（オリジナル比1.5倍。さらに調整したい場合は本文・見出しを比例して変更）:

| クラス | 用途 | font-size |
|---|---|---|
| `.text-page` | 本文（目次・コラム・著者紹介等） | 42px |
| `.text-page h2` | 大見出し | 54px |
| `.text-page h3` | 小見出し | 45px |
| `.text-page .subtitle` | サブタイトル・肩書き | 33px |
| `.colophon` | 奥付本文 | 45px |
| `.colophon h2` | 奥付見出し | 54px |

#### EPUB生成スクリプト

```bash
python << 'PYTHON_SCRIPT'
import zipfile
import os
import glob
import uuid
import urllib.request
from datetime import datetime

BOOK_NAME = "{{book-name}}"
TITLE = "マンガでわかる {{元タイトル}}"
AUTHOR = "{{著者名}}"
OUTPUT_DIR = r"{{出力ディレクトリ}}"
PAGES_DIR = os.path.join(OUTPUT_DIR, "panels", "pages")
COVER_PATH = os.path.join(OUTPUT_DIR, "KDP出版用", "cover.png")
EPUB_PATH = os.path.join(OUTPUT_DIR, "KDP出版用", f"{BOOK_NAME}-manga.epub")

# --- Noto Sans JP フォントを取得（キャッシュ） ---
FONT_CACHE = os.path.join(os.path.expanduser("~"), ".cache", "noto-sans-jp")
os.makedirs(FONT_CACHE, exist_ok=True)
FONT_URLS = {
    "NotoSansJP-Regular.otf": "https://github.com/notofonts/noto-cjk/raw/main/Sans/SubsetOTF/JP/NotoSansJP-Regular.otf",
    "NotoSansJP-Bold.otf":    "https://github.com/notofonts/noto-cjk/raw/main/Sans/SubsetOTF/JP/NotoSansJP-Bold.otf",
}
font_paths = {}
for fname, url in FONT_URLS.items():
    fpath = os.path.join(FONT_CACHE, fname)
    if not os.path.exists(fpath) or os.path.getsize(fpath) < 1_000_000:
        urllib.request.urlretrieve(url, fpath)
    font_paths[fname] = fpath

# ページ画像の収集（ソート済み）
# Step 5 はEPUB用に JPEG (.jpg) を作成するため .jpg を対象とする
# JPEG版がない場合は、事前にPNG原本から同寸法JPEGへ変換してから製本する
page_files = sorted(glob.glob(os.path.join(PAGES_DIR, "page_*.jpg")))
page_count = len(page_files)
book_id = str(uuid.uuid4())
modified = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")

# --- mimetype ---
mimetype = "application/epub+zip"

# --- container.xml ---
container_xml = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""

# --- style.css ---
# Noto Sans JP を埋め込み、テキストページは1.5倍サイズで読みやすくレンダリング
style_css = """@charset "UTF-8";
@font-face {
  font-family: "Noto Sans JP";
  font-weight: normal;
  font-style: normal;
  src: url("fonts/NotoSansJP-Regular.otf") format("opentype");
}
@font-face {
  font-family: "Noto Sans JP";
  font-weight: bold;
  font-style: normal;
  src: url("fonts/NotoSansJP-Bold.otf") format("opentype");
}
html, body { margin: 0; padding: 0; width: 100%; height: 100%; background-color: #ffffff; }
.page { width: 100%; height: 100%; position: relative; text-align: center; }
.page img { display: block; height: 100%; width: auto; max-width: 100%; margin: 0 auto; }
.text-page {
  padding: 3% 5%;
  font-family: "Noto Sans JP", "Hiragino Kaku Gothic ProN", "Yu Gothic", sans-serif;
  font-size: 42px;
  line-height: 1.5;
  color: #333;
  box-sizing: border-box;
}
.text-page h2 { font-size: 54px; margin: 0 0 12px 0; border-bottom: 2px solid #ddd; padding-bottom: 6px; }
.text-page h3 { font-size: 45px; margin-top: 14px; margin-bottom: 6px; }
.text-page p { margin: 5px 0; text-indent: 1em; }
.text-page .subtitle { font-size: 33px; color: #666; font-style: italic; margin-bottom: 12px; text-indent: 0; }
.colophon {
  padding: 5% 7%;
  font-family: "Noto Sans JP", "Hiragino Kaku Gothic ProN", "Yu Gothic", sans-serif;
  font-size: 45px;
  line-height: 1.5;
  color: #333;
}
.colophon h2 { font-size: 54px; margin: 14px 0 6px 0; border-bottom: 2px solid #ddd; padding-bottom: 4px; }
.colophon h2:first-child { margin-top: 0; }
.colophon p { margin: 4px 0; text-indent: 0; }
"""

# --- content.opf ---
manifest_items = [
    '    <item id="nav" href="text/nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
    '    <item id="style" href="style.css" media-type="text/css"/>',
    '    <item id="font-noto-regular" href="fonts/NotoSansJP-Regular.otf" media-type="application/vnd.ms-opentype"/>',
    '    <item id="font-noto-bold" href="fonts/NotoSansJP-Bold.otf" media-type="application/vnd.ms-opentype"/>',
    '    <item id="cover-image" href="images/cover.png" media-type="image/png" properties="cover-image"/>',
    '    <item id="cover" href="text/cover.xhtml" media-type="application/xhtml+xml"/>',
]
spine_items = ['    <itemref idref="cover"/>']

for i in range(1, page_count + 1):
    pid = f"page_{i:03d}"
    manifest_items.append(f'    <item id="{pid}" href="text/{pid}.xhtml" media-type="application/xhtml+xml"/>')
    manifest_items.append(f'    <item id="{pid}-img" href="images/{pid}.png" media-type="image/png"/>')
    spine_items.append(f'    <itemref idref="{pid}"/>')

content_opf = f"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="BookId" prefix="rendition: http://www.idpf.org/vocab/rendition/#">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="BookId">{book_id}</dc:identifier>
    <dc:title>{TITLE}</dc:title>
    <dc:creator>{AUTHOR}</dc:creator>
    <dc:language>ja</dc:language>
    <meta property="dcterms:modified">{modified}</meta>
    <meta property="rendition:layout">pre-paginated</meta>
    <meta property="rendition:spread">landscape</meta>
    <meta name="cover" content="cover-image"/>
  </metadata>
  <manifest>
{chr(10).join(manifest_items)}
  </manifest>
  <spine page-progression-direction="rtl">
{chr(10).join(spine_items)}
  </spine>
</package>"""

# --- nav.xhtml ---
nav_xhtml = f"""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="ja">
<head><title>{TITLE}</title></head>
<body>
<nav epub:type="toc">
  <ol>
    <li><a href="cover.xhtml">表紙</a></li>
    <li><a href="page_001.xhtml">本編</a></li>
  </ol>
</nav>
</body>
</html>"""

# --- ページXHTML生成関数 ---
def make_page_xhtml(img_path, alt_text):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" lang="ja">
<head>
  <meta name="viewport" content="width=1080, height=1920"/>
  <link rel="stylesheet" href="../style.css"/>
  <title>{alt_text}</title>
</head>
<body>
  <div class="page"><img src="{img_path}" alt="{alt_text}"/></div>
</body>
</html>"""

# --- EPUB書き出し ---
os.makedirs(os.path.dirname(EPUB_PATH), exist_ok=True)

with zipfile.ZipFile(EPUB_PATH, 'w') as epub:
    # mimetype は非圧縮で最初に追加
    epub.writestr("mimetype", mimetype, compress_type=zipfile.ZIP_STORED)
    epub.writestr("META-INF/container.xml", container_xml, compress_type=zipfile.ZIP_DEFLATED)
    epub.writestr("OEBPS/content.opf", content_opf, compress_type=zipfile.ZIP_DEFLATED)
    epub.writestr("OEBPS/text/nav.xhtml", nav_xhtml, compress_type=zipfile.ZIP_DEFLATED)
    epub.writestr("OEBPS/style.css", style_css, compress_type=zipfile.ZIP_DEFLATED)

    # フォント埋め込み（既圧縮なので ZIP_STORED で格納）
    for fname, fpath in font_paths.items():
        epub.write(fpath, f"OEBPS/fonts/{fname}", compress_type=zipfile.ZIP_STORED)

    # 表紙
    epub.write(COVER_PATH, "OEBPS/images/cover.png", compress_type=zipfile.ZIP_DEFLATED)
    cover_xhtml = make_page_xhtml("../images/cover.png", "表紙")
    epub.writestr("OEBPS/text/cover.xhtml", cover_xhtml, compress_type=zipfile.ZIP_DEFLATED)

    # 各ページ（Step 5 が page_{NNN}.jpg（JPEG）をEPUB用に保存するため .jpg で格納）
    for i, page_file in enumerate(page_files, 1):
        pid = f"page_{i:03d}"
        epub.write(page_file, f"OEBPS/images/{pid}.jpg", compress_type=zipfile.ZIP_DEFLATED)
        page_xhtml = make_page_xhtml(f"../images/{pid}.jpg", f"ページ {i}")
        epub.writestr(f"OEBPS/text/{pid}.xhtml", page_xhtml, compress_type=zipfile.ZIP_DEFLATED)

print(f"OK: {EPUB_PATH}")
print(f"Pages: {page_count}")
print(f"Size: {os.path.getsize(EPUB_PATH) / 1024 / 1024:.1f} MB")
PYTHON_SCRIPT
```

#### EPUB仕様
- **固定レイアウト**: `rendition:layout: pre-paginated`
- **ページ方向**: `page-progression-direction: rtl`（右開き）
- **ビューポート**: `1080x1920`（9:16）
- **各ページ**: フルビューポート画像1枚

#### Step 5 QCループとの下流互換性

Step 5 の QC ループは `pages/page_{NNN}.png` を原本として出力し、QC PASS後に `pages/page_{NNN}.jpg` をEPUB用として出力する。
本 EPUB 生成スクリプトは `glob("page_*.jpg")` でこのファイル群を収集する。

| Step 5 出力パターン | EPUB に含まれるファイル | 対応方法 |
|---|---|---|
| PASS ページ | `page_{NNN}.jpg`（収束 iter のPNG原本から変換済み） | そのまま収集 |
| blocked ページ | なし | EPUB化へ進まない（解消後に本ステップを再実行） |
| 中間ファイル（`_iter_*`） | `glob` パターンに一致しないため自動除外 | 対応不要 |

> **前提**: Step 5 の責務として、`blocked_pages` が空であり全ページの `page_{NNN}.jpg` が揃っていることを確認してから本ステップを実行すること。PNG原本は再変換・監査用に残す。

---

### Step 8: 電子出版用メタデータ

KDP出版に必要なメタデータを生成する。既存の `.company/outputs/ebooks/` 内のKDPメタデータ形式に準拠する。

#### 8-1. 書籍情報.md

```markdown
# 書籍情報

## タイトル
- **日本語**: マンガでわかる {元タイトル}
- **フリガナ**: {フリガナ}
- **ローマ字**: {ローマ字}

## サブタイトル
- **日本語**: {元サブタイトル}【マンガ版】
- **フリガナ**: {フリガナ}
- **ローマ字**: {ローマ字}

## 著者名
- **日本語**: {著者名}
- **フリガナ**: {フリガナ}
- **ローマ字**: {ローマ字}

## 出版社名
- **日本語**: YN出版
- **フリガナ**: ワイエヌシュッパン
- **ローマ字**: YN Shuppan
```

#### 8-2. ジャンル・キーワード.md

- メインジャンル + サブジャンルを設定
- キーワード7枠 × 3ワード = 21ワード
- マンガ固有キーワードを必ず含める: `マンガ`, `漫画`, `マンガでわかる`, `図解`, `コミック`
- 元書籍のキーワードも活用する

#### 8-3. 書籍紹介文_HTML.html

KDP商品説明欄にそのまま貼り付けられるHTML形式で作成する（必須）。
上記「標準保存ルール」の書籍紹介文_HTML.htmlフォーマットに準拠すること。

#### 出力先
- `KDP出版用/書籍情報.md`
- `KDP出版用/ジャンル・キーワード.md`
- `KDP出版用/書籍紹介文_HTML.html`

---

## 作画設定マスタ

書籍テーマに応じて、以下の20ジャンルから最適な作画設定を自動選択する。
（出典: `C:\Users\User\OneDrive - 株式会社　美建\作画設定.xlsx`）

### 恋愛ドラマ
- ジャンル: 恋愛に最適化した統一スタイル
- 作画スタイル: 現代的でクリアなアニメ調,細く滑らかな線画
- 色調: パステルカラー基調,温かみのある色彩
- 線画: 細く繊細な線,ハイライトを効果的に使用
- 演出: 桜の花びら,キラキラエフェクト,ソフトフォーカス,必要に応じて集中線,効果線,擬音などのマンガらしい演出

### 異世界バトルもの
- ジャンル: 異世界バトルものに最適化した統一スタイル
- 作画スタイル: 劇画調,筋肉質な体型表現,迫力重視
- 色調: 濃い色彩,コントラスト強め,炎や雷などの鮮やかなエフェクト
- 線画: 太く力強い線,影を多用したメリハリのある表現
- 演出: 集中線,爆発エフェクト,スピード線を多用,必要に応じて集中線,効果線,擬音などのマンガらしい演出

### ミステリー
- ジャンル: ミステリーに最適化した統一スタイル
- 作画スタイル: リアル寄り,細密な描写,大人っぽい表現
- 色調: モノトーン基調,深い青や紫,影を効果的に使用
- 線画: 細く繊細な線,陰影を重視した立体感
- 演出: 暗い照明,逆光,不安を煽る構図,必要に応じて集中線,効果線,擬音などのマンガらしい演出

### ビジネス
- ジャンル: ビジネスに最適化した統一スタイル
- 作画スタイル: 現実的,スーツ姿の正確な描写,清潔感重視
- 色調: 落ち着いた色調,グレー・ネイビー・白基調
- 線画: 整った線,クリーンな表現
- 演出: オフィス空間,グラフや資料の描写,必要に応じて集中線,効果線,擬音などのマンガらしい演出

### 哲学思想
- ジャンル: 哲学・思想に最適化した統一スタイル
- 作画スタイル: 抽象的表現も含む,象徴的な描写
- 色調: 落ち着いた色調,モノクロ部分も効果的に使用
- 線画: 繊細で思慮深い表現
- 演出: 思考を表現する視覚効果,メタファー的な背景,必要に応じて集中線,効果線,擬音などのマンガらしい演出

### 解説教育
- ジャンル: 解説・教育に最適化した統一スタイル
- 作画スタイル: 分かりやすく親しみやすい表現
- 色調: 明るく見やすい色調,重要部分は強調色
- 線画: はっきりとした線,読みやすさ重視
- 演出: 図解,矢印,吹き出しを多用,情報整理重視,必要に応じて集中線,効果線,擬音などのマンガらしい演出

### ホラー
- ジャンル: ホラーに最適化した統一スタイル
- 作画スタイル: 不気味さを強調,歪んだ表現,リアルな恐怖描写
- 色調: 暗い色調,黒・赤・灰色基調,不自然な影
- 線画: 不規則で荒々しい線,ざらついた質感
- 演出: 血しぶき,暗闇,突然の視点変化,恐怖を煽る構図,必要に応じて集中線,効果線,擬音などのマンガらしい演出

### スポーツ
- ジャンル: スポーツに最適化した統一スタイル
- 作画スタイル: 躍動感重視,筋肉や動きの正確な描写
- 色調: 鮮やかで活力ある色彩,汗や光の表現
- 線画: 力強く流れるような線,動きを強調
- 演出: スピード線,汗の飛沫,躍動感のある構図,観客の歓声,必要に応じて集中線,効果線,擬音などのマンガらしい演出

### SF・宇宙
- ジャンル: SF・宇宙に最適化した統一スタイル
- 作画スタイル: 未来的でメカニカル,精密な機械描写
- 色調: メタリック,ネオンカラー,青・銀・黒基調
- 線画: シャープで精密な線,テクノロジー感
- 演出: ホログラム,光の粒子,宇宙空間,未来的UI表示,必要に応じて集中線,効果線,擬音などのマンガらしい演出

### 日常コメディ
- ジャンル: 日常コメディに最適化した統一スタイル
- 作画スタイル: デフォルメ表現多用,親しみやすいキャラデザイン
- 色調: 明るくポップな色彩,カラフルで楽しい雰囲気
- 線画: 柔らかく丸みのある線,表情豊かな描写
- 演出: 汗マーク,びっくりマーク,コミカルな効果音,誇張表現,必要に応じて集中線,効果線,擬音などのマンガらしい演出

### 時代劇・歴史
- ジャンル: 時代劇・歴史に最適化した統一スタイル
- 作画スタイル: 伝統的な劇画調,時代考証を重視した描写
- 色調: 落ち着いた和の色調,茶・黒・金・朱色基調
- 線画: 太く重厚な線,墨絵風の表現も取り入れる
- 演出: 桜吹雪,刀の軌跡,和風エフェクト,時代背景の細密描写,必要に応じて集中線,効果線,擬音などのマンガらしい演出

### サスペンス・スリラー
- ジャンル: サスペンス・スリラーに最適化した統一スタイル
- 作画スタイル: 緊張感のあるリアル描写,心理的圧迫感
- 色調: 暗めの色調,赤・黒・グレー基調,不安を煽る配色
- 線画: 鋭く緊張感のある線,影を効果的に使用
- 演出: 斜めの構図,クローズアップ,時計や心拍数の視覚化,必要に応じて集中線,効果線,擬音などのマンガらしい演出

### ファンタジー・冒険
- ジャンル: ファンタジー・冒険に最適化した統一スタイル
- 作画スタイル: 幻想的で壮大,魔法や異世界の表現
- 色調: 鮮やかで神秘的,緑・青・金・紫基調
- 線画: 流麗で装飾的な線,ファンタジー要素の細密描写
- 演出: 魔法陣,光の粒子,幻想的な背景,壮大な風景,必要に応じて集中線,効果線,擬音などのマンガらしい演出

### グルメ・料理
- ジャンル: グルメ・料理に最適化した統一スタイル
- 作画スタイル: 料理の質感を重視,美味しそうな表現
- 色調: 暖色系中心,食欲をそそる色彩,艶や湯気の表現
- 線画: 丁寧で繊細な線,料理の細部まで描写
- 演出: 湯気,光沢,断面図,食べる瞬間の表情,キラキラエフェクト,必要に応じて集中線,効果線,擬音などのマンガらしい演出

### 青春・学園
- ジャンル: 青春・学園に最適化した統一スタイル
- 作画スタイル: 爽やかで清潔感のある表現,制服の正確な描写
- 色調: 明るく爽やかな色調,青空・白・緑基調
- 線画: クリアで整った線,若々しい表現
- 演出: 青空,校舎,桜,夕焼け,青春を象徴する背景,必要に応じて集中線,効果線,擬音などのマンガらしい演出

### サイバーパンク
- ジャンル: サイバーパンクに最適化した統一スタイル
- 作画スタイル: 退廃的で未来的,ハイテクとローライフの融合
- 色調: ネオン,ピンク・青・紫基調,雨や夜の都市
- 線画: シャープで複雑な線,機械と人体の融合表現
- 演出: ネオンサイン,雨,ホログラム,電脳空間,都市の雑踏,必要に応じて集中線,効果線,擬音などのマンガらしい演出

### 投資
- ジャンル: 投資に最適化した統一スタイル
- 作画スタイル: 信頼感と専門性を重視,データやグラフの視覚化
- 色調: 落ち着いた色調,紺・緑・金・グレー基調,成長を示す上昇カラー
- 線画: クリアで正確な線,図表やチャートの明瞭な描写
- 演出: 株価チャート,グラフ,矢印,数字の強調,成功イメージの背景,必要に応じて集中線,効果線,擬音などのマンガらしい演出

### 副業
- ジャンル: 副業に最適化した統一スタイル
- 作画スタイル: 親しみやすく実践的,現代的なライフスタイル表現
- 色調: 明るく前向きな色調,オレンジ・青・黄色基調,活力ある配色
- 線画: 親しみやすい柔らかな線,カジュアルで読みやすい表現
- 演出: パソコン作業,スマホ,時計,収入の可視化,ステップ図解,必要に応じて集中線,効果線,擬音などのマンガらしい演出

### 趣味
- ジャンル: 趣味に最適化した統一スタイル
- 作画スタイル: 楽しさと充実感を重視,趣味の道具や活動の丁寧な描写
- 色調: 温かく楽しい色調,多彩な色彩,趣味に応じた適切な配色
- 線画: 柔らかく親しみやすい線,細部まで愛情を込めた描写
- 演出: キラキラエフェクト,笑顔,充実感の表現,趣味の道具や成果物,必要に応じて集中線,効果線,擬音などのマンガらしい演出

### 論文・学術
- ジャンル: 論文・学術に最適化した統一スタイル
- 作画スタイル: 学術的で正確な表現,研究内容の視覚化重視
- 色調: 知的で落ち着いた色調,白・青・グレー基調,アカデミックな雰囲気
- 線画: 精密で正確な線,図表やデータの明瞭な描写
- 演出: 研究データ,グラフ,数式,引用表示,論理的な構成の可視化

---

## 進捗管理

`progress.json` でパイプラインの進捗を管理する。セッション中断時の再開に使用。

```json
{
  "book_name": "01-worker-positive",
  "source_path": ".company/outputs/ebooks/01-worker-positive/",
  "target_pages": 100,
  "genre": "ビジネス",
  "steps": {
    "1_source": {"status": "done", "completed_at": "2026-03-24T10:00:00"},
    "2_scenario": {"status": "done", "characters": ["健太", "理沙", "教授"]},
    "3_characters": {"status": "done", "images": ["健太.png", "理沙.png", "教授.png"]},
    "4_panels": {"status": "done", "page_count": 100},
    "5_images": {"status": "in_progress", "completed": 40, "total": 100, "failed": [23, 67]},
    "6_cover": {"status": "pending"},
    "7_epub": {"status": "pending"},
    "8_metadata": {"status": "pending"}
  }
}
```

---

## 生成量・所要時間の目安

このスキルでは画像生成にAPIを使わないため、API従量課金の見積もりは作らない。

| 項目 | 枚数（100ページの場合） | 目安 |
|------|----------------------|------|
| Step 5: ページ画像（平均1.5 iter） | 100 × 1.5 = 150 | ChatGPT/Codex側で順次生成 |
| Step 3: キャラリファレンス | 2-3 | 参照画像として保存 |
| Step 6: 表紙 | 1 | KDP用PNG/JPEGに変換 |
| Step 5-QC: Blind-OCR / Vision-check | 生成枚数分 | ChatGPT/Codex上の視覚確認またはローカルOCR |

所要時間は生成待ち時間と再生成回数に依存する。100枚規模では数十分以上を見込む。

---

## エラーハンドリング

| エラー | 対処 |
|--------|------|
| ソースフォルダが見つからない | エラー表示し、利用可能なebookフォルダを一覧する |
| ChatGPT Images 2.0生成に失敗 | 失敗ページをログに記録し、同じセッション内でプロンプトを調整して再生成する。max_iter 超過時は `blocked_gpt_image2_web` として止める |
| EPUB構築エラー | エラー詳細を表示し、画像ファイルの存在を確認 |
| ページ数超過 | Step 2のシナリオを凝縮して再生成 |
| キャラ外見の不一致 | キャラ定義の詳細を強化してプロンプトを再生成 |
| **codex-handoff: done/<job-id>/progress.json が出現しない** | 現在の標準運用ではhandoffを使わない。ユーザーが明示的にhandoffを指定した場合のみ、Codex側の進行状況を確認する |
| **codex-handoff: progress.json の status が "failed"** | `.company/codex/done/<job-id>/progress.json` の `errors[]` を確認し、ユーザーに通知する。新 job-id で queue に再投入するか手動対応を促す |
| **codex-handoff: blocked_pages が多数** | ユーザーに該当ページ番号リストを提示する。再生成する場合は新 job-id で該当ページのみを manifest に含めて再投入する。blocked が解消するまで EPUB 化に進まない |
| **codex-handoff: partial（部分生成）** | `progress.json` の `status: "partial"` を検出したら不足 items を確認し、ユーザーに通知する。新 job-id で不足分のみを manifest に含めて再投入する |

## 注意事項

- Windows環境では `python3` ではなく `python` を使用する
- 100枚規模の画像生成は時間がかかるため、進捗を `progress.json` に記録しながら進める
- 生成画像の品質にはばらつきがある: QCループ（Step 5）が自動的にリトライを行う。max_iter 超過ページは `blocked_gpt_image2_web` として止まり、progress.json の blocked_pages で確認できる。blocked が空になるまで EPUB 化しない
- 固定レイアウトEPUBはKindle Unlimitedの対象外となる場合がある（KDPの最新規約を確認）
- EPUBの表示確認はKindleプレビューアで必ず行うこと

---

## E2E動作確認手順

### 目的

QCパイプライン（工程1〜5の本実装成果）が実データで期待通り動作することを確認する。
Step 4 の `コマ別テキストJSON` → Step 5 の Blind-OCR 判定 → Web再生成または `blocked_gpt_image2_web`
という一連のデータフローが途切れなく機能していることを担保する。

---

### 確認項目

#### 1. CSV生成確認（Step 4）

Step 4 完了後に `panels/comicle_output.csv` を開き、以下を確認する。

- ヘッダーが 5 列（`ページ番号,使用するコマ割りテンプレ,漫画作成のプロンプト,コマ別テキストJSON,outfit_id`）になっていること
- テキストを含むページの `コマ別テキストJSON` 列が JSON 配列として格納されていること
  - 例: `[{"panel_id": 1, "type": "dialogue", "speaker": "ミサキ", "text": "えっ、本当に？"}]`
- テキストページの `コマ別テキストJSON` 列が空配列 `[]` になっていること
- JSON 内に生のダブルクォート（`"`）が混入していないこと（〝〟に変換済みであること）

**確認コマンド（Python）:**
```python
import csv, json

with open("panels/comicle_output.csv", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for i, row in enumerate(reader, 1):
        raw = row.get("コマ別テキストJSON", "[]")
        # 〝〟を " に戻してパース
        normalized = raw.replace("\u301d", '"').replace("\u301f", '"')
        try:
            items = json.loads(normalized)
            print(f"page {i:03d}: OK ({len(items)} items)")
        except json.JSONDecodeError as e:
            print(f"page {i:03d}: PARSE ERROR - {e}")
```

---

#### 2. OCR判定確認（Step 5 / Step 5-QC）

Step 5 の Blind-OCR が正しく動作していることを確認する。

**確認ステップ:**

1. 生成済みページ画像（例: `pages/page_039_iter_1.png`）を使って Step 5-QC の OCR プロンプトを単体実行する
2. レスポンスが `{"bubbles": [...]}` の JSON 形式で返ること
3. OCR 結果の `detected_text` が CSV の `text` フィールドと一致（または不一致）することを確認する

**重要チェック**: プロンプトに期待テキスト（CSV の `text` フィールド値）が含まれていないこと（confirmation bias 排除）。

**確認用プロンプト:**
```text
添付のマンガ画像を見て、吹き出し（楕円・雲形）と
ナレーションボックス（四角枠）の文字を画像に見える通り正確に読み取ってください。
推測・補完禁止。

出力形式: JSONのみ。
{"bubbles": [{"panel_id": 1, "type": "dialogue"|"narration", "detected_text": "..."}]}
```

APIは使わず、生成済みページ画像をChatGPT/Codex上で表示して上記プロンプトに沿って確認する。

---

#### 3. フィードバック注入確認（Step 5 FAIL 時）

FAIL 時に次 iter のプロンプトに FAIL 内容が反映されることを確認する。

**確認方法:**

1. iter=1 で FAIL したページのログを確認する（例: `[iter 1] FAIL: panel=2 type=dialogue ...`）
2. iter=2 の生成プロンプトに以下のセクションが含まれることを確認する:
   ```
   ◆【前回失敗・最重要】前回生成では以下が正しく描画されませんでした。今回は一字一句正確に描くこと:
   - パネル2のセリフ: 正「...」 ⇔ 前回誤「...」
   ```
3. iter=2 の生成画像で当該パネルのテキストが改善されていることを目視確認する

---

#### 4. blocked確認（max_iter 超過時）

`max_iter` 超過時に該当ページが `blocked_gpt_image2_web` として止まることを確認する。

**確認ステップ:**

1. `max_iter` を一時的に `1` に設定して難ページ（例: ページ39）を単体実行する
   ```python
   # Step 5 のループ引数で max_iter=1 を指定
   max_iter = 1
   ```
2. iter=1 が FAIL した場合、以下が行われることを確認する:
   - `pages/page_039_iter_1.png`（監査用。iter=1 の生成画像）が存在すること
   - `pages/page_039.png` が作成されていないこと（blocked ページを最終成果物にしない）
   - `prompts/page_039_blocked_prompt.txt` に最終プロンプトが保存されていること
   - `progress.json` の `blocked_pages` に `39` が追加されていること
   - ログに `[blocked] page 039: gpt_image2_web blocked` が出力されていること

**目視確認ポイント:**
- blocked ページが EPUB 入力として使用されないこと（`blocked_pages` が空になるまで Step 7 に進まないこと）
- `progress.json` の `blocked_reasons["39"]` に理由（`"ocr_fail"` / `"vision_fail"` / `"both_fail"`）が記録されていること

---

#### 5. progress.json確認

`progress.json` が正しく更新されていることを確認する。

**正常系（A路線 PASS の場合）:**
```json
"5_images": {
  "status": "in_progress",
  "completed": 39,
  "total": 100,
  "failed": []
}
```

**blocked発生時:**
```json
"5_images": {
  "status": "in_progress",
  "completed": 98,
  "total": 100,
  "failed": [],
  "blocked_pages": [39, 52],
  "blocked_reasons": {"39": "ocr_fail", "52": "vision_fail"}
}
```

- `blocked_pages` リストに blocked ページが記録されていること
- PASS したページは `failed` に記録されないこと（iter 超過したページは `blocked_pages` に記録）
- `blocked_pages` が空でない間は Step 5 を `done` にせず、Step 7 に進まないこと

---

#### 6. 下流工程非破壊確認（Step 6 / Step 7 / Step 8）

ハイブリッドQCループの追加が Step 6 以降に影響を与えないことを確認する。

**Step 6（表紙作成）:**
- Step 6 は `pages/` フォルダを参照しないため影響なし
- `KDP出版用/cover.png` が正常に生成されることを確認する
- `KDP出版用/cover.jpg` が同寸法で生成されることを確認する

**Step 7（EPUB製本）:**
- `panels/pages/page_{NNN}.jpg`（3桁ゼロ埋め）ファイルが全ページ分存在することを確認する
- JPEG版の容量と文字可読性を確認する。必要に応じて品質85〜92の範囲で再変換する
- blocked ページが残っていないこと（`blocked_pages` が空であること）
- `_iter_*.png` 等の中間ファイルは `page_*.jpg` のワイルドカードには一致しないため自動的に除外される
- EPUB 生成スクリプトが `glob("page_*.jpg")` で正しい枚数を収集できることを確認する

**Step 8（メタデータ）:**
- Step 8 は画像ファイルを参照しないため影響なし
- `KDP出版用/書籍情報.md` / `ジャンル・キーワード.md` / `書籍紹介文_HTML.html` が正常生成されることを確認する

---

#### 7. Vision-check 単体動作確認

**確認ステップ:**

1. セリフなしページ（例: page_002 登場人物紹介ページ）を対象として、キャラを1人意図的に欠落させた画像を用意する
   - 欠落させ方: 例えば山田課長の画像スロットを空欄またはテキスト枠のみにした画像を用意する
2. Vision-check を単体実行して `vision_check()` 関数を呼び出す
3. Vision-check が FAIL を返し、`missing_chars` に欠落キャラ名が含まれることを確認する
4. Step 5 のループで再生成がトリガーされることをログで確認する
   - 期待ログ: `[vision] FAIL: page=002 missing=[山田課長]`
   - 期待ログ: `[iter 2] 再生成開始（Vision-check FAIL: missing=[山田課長]）`

---

#### 8. OCR × Vision-check 独立性確認

**確認ステップ:**

1. セリフありページを1件選び、OCR は PASS するが Vision-check は FAIL になる人工ケースを作成する
   - 例: テキストが正確に描かれているがキャラの1人がテキスト枠のみで描かれていない画像を用意する
2. Step 5 のループで OCR 判定 → Vision-check 判定を順に実行する
3. OCR PASS / Vision-check FAIL のケースでも**ページ全体が FAIL** 判定になることを確認する
   - 期待ログ: `[ocr] iter_1 result=PASS`、`[vision] FAIL: page={NNN} missing=[...]`
   - 期待ログ: `[iter 1] ページ判定: FAIL（OCR=PASS, Vision=FAIL）→ 再生成`

---

#### 9. テキストページの自動スキップ確認

**確認ステップ:**

1. `コマ別テキストJSON` が `[]` のテキストページ（画像生成スキップ対象）を指定して Step 5 を実行する
2. 画像生成・OCR・Vision-check すべてがスキップされ、自動 PASS として `progress.json` に記録されることを確認する
   - 期待ログ: `[skip] page={NNN}: テキストページ（画像生成スキップ済み）→ 自動 PASS`

---

### 合格基準

以下をすべて満たした場合に E2E 確認完了とする。

| 確認項目 | 合格条件 |
|---|---|
| CSV生成 | `コマ別テキストJSON` 列が全ページで有効な JSON（または空配列） |
| OCR判定 | Blind-OCR が期待テキストなしで正しく読み取り PASS/FAIL を判定 |
| フィードバック注入 | FAIL 時に `◆【前回失敗・最重要】` セクションが次 iter のプロンプトに含まれる |
| blocked管理 | max_iter 超過時に該当ページが `blocked_gpt_image2_web` として止まり、`blocked_pages` が空になるまで EPUB 化しない |
| progress.json | `blocked_pages` / `blocked_reasons` / `vision_check_failed_pages` が記録され、EPUB Step 7 で参照可能な状態 |
| ファイル命名 | 全ページが `pages/page_{NNN}.png` として揃っている（中間ファイルは除外） |
| EPUB生成 | Step 7 が変更なく動作し、正常な EPUB が出力される |
| KDPメタデータ | Step 8 が変更なく動作し、書籍情報・紹介文が出力される |
| 日本語テキスト | 全ページのセリフ・ナレーションが Blind-OCR PASS で処理済み（blocked ページは解消済みであること） |
| Vision-check 単体動作 | セリフなしページでキャラ欠落を Vision-check が FAIL 検出し再生成ループが発動する |
| OCR × Vision-check 独立性 | OCR PASS / Vision-check FAIL のケースでもページ全体が FAIL 判定になる |
| テキストページスキップ | `コマ別テキストJSON == []` のページで OCR・Vision-check 両方スキップ・自動 PASS になる |
