---
name: ebook-to-manga
description: 既存のKindle電子書籍（Markdown原稿。project.md + manuscript/構成）をマンガ形式に変換し、EPUB化してKDP出版用メタデータまで一括生成するスキル。ChatGPT Pro Web / ChatGPT Images 2.0 (gpt-image-2) 画像生成、コミクル2.0テンプレートを組み合わせた8ステップパイプライン（ソース分析→シナリオ→キャラデザ→コマ割りCSV→画像生成→表紙→EPUB製本→メタデータ）。ユーザーが「マンガ化して」「マンガ版を作って」と依頼したとき、またはebook-from-themeが生成したproject.md+manuscript/一式を漫画化するときに使う。詳細仕様は`references/`配下の各ファイルを参照。
---

# 電子書籍マンガ化スキル (Ebook-to-Manga Converter)

## 概要

既存のKindle電子書籍（Markdown原稿）をマンガ形式の電子書籍に変換する。8ステップのパイプラインでソース分析からKDP出版準備まで一気通貫で実行する。詳細仕様が長いステップは `references/` 配下の対応ファイルに分割してあるため、各ステップ実行時は本体の要点だけでなく参照先ファイルも必ず読み込むこと。

## 入力

- **ソースフォルダ**（必須）: ebookフォルダのパス（例: `.company/outputs/ebooks/01-worker-positive/`）。`project.md` と `manuscript/` ディレクトリを含むこと。
- **目標ページ数**（任意）: デフォルト100。範囲40-120。
- **ジャンル指定**（任意）: 作画設定の20ジャンルから指定。未指定時は書籍テーマから自動判定。
- **出力フォルダ名**（任意）: `.company/outputs/ebooks-manga/` 配下。デフォルトはソースフォルダ名。

## 前提条件

- ChatGPT Pro Web にログイン済みで、ChatGPT Images 2.0 / `gpt-image-2` を使えること（必須）
- Python 3.x が `python` コマンドで利用可能なこと（Windows環境）
- `GOOGLE_AI_STUDIO_API_KEY` 環境変数 / `google-genai` パッケージ（任意・レガシー。移行後別PRで整理予定）

## 画像生成の実行ルール

本スキルの画像生成は ChatGPT Pro Web / ChatGPT Images 2.0 / `gpt-image-2` のみを使用する。
- OpenAI Images API、`OPENAI_API_KEY`、OpenAI SDK、`client.images.generate/edit` は使わない。
- `openai-image-gen` の旧API実行へ切り替えない。
- Pillow・ローカル手続き生成・プレースホルダー画像を最終ページや最終表紙として使わない。
- ChatGPT Pro Webで生成できない場合は、プロンプト・参照画像・manifestを保存し、`pending_gpt_image2_web` または `blocked_gpt_image2_web` として止める。

旧 `HANDOFF_MODE=inline` / `codex-handoff`、APIハンドオフ、Pillow合成フォールバックは廃止済みの旧仕様として扱う。現在の実行時に参照・復活させない。

---

## 画像生成の絶対ルール

- **全ステップ共通**: 画像生成時は必ず「日本のアニメ・マンガ調イラスト」で生成すること
- 実写風・フォトリアル風の画像は禁止
- プロンプトの冒頭に必ず「◆【絶対最優先】必ず日本のアニメ・マンガ調のイラストで描いてください。実写風・フォトリアル風は禁止です。」を含めること
- これはキャラクターデザイン（Step 3）、ページ画像（Step 5）、表紙（Step 6）すべてに適用する

## 画像フォーマット

- **Step 5 本文ページ画像はPNG形式（.png）で保存する**
- **Step 6 表紙もPNG形式（.png）で保存する**。KDP用に別形式が必要な場合も、Pillowで作った画像を最終表紙扱いしない
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
├── vol1/                           # 第1巻（vol2, vol3... も同一構造）
│   ├── panels/
│   │   └── comicle_output.csv
│   ├── pages/
│   │   ├── page_001.png ... page_NNN.png
│   └── KDP出版用/
│       ├── {タイトル} 第1巻.epub
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

**書籍情報.md のフォーマット（必須）:** タイトル・サブタイトル・著者名・出版社名を「日本語・フリガナ（カタカナ）・ローマ字」の3形式で記載する。実フォーマットは Step 8-1（後述）を参照。出版社名は既定 `YN出版`（フリガナ: ワイエヌシュッパン、ローマ字: YN Shuppan）。

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

以下のペルソナと指示に基づいて、Codexがマンガ用シナリオを作成する。

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

第N章：{章タイトル}
{第N章の文章形式シナリオ}（書籍の章数分繰り返す）

エピローグ：{エピローグタイトル}
{エピローグの文章形式シナリオ}
```

#### 出力
- ファイル: `manuscript/シナリオ.txt`
- **ユーザー確認ポイント**: シナリオの内容を表示し、登場人物・ストーリー展開の確認を得る

---

### Step 3: キャラクターデザイン

シナリオの登場人物（最大3名）ごとにキャラクターデザインを生成する。

> **現行フロー概要**
> - 3-1 キャラクター定義 → 3-2-A プロンプト構築 → 3-2-B ChatGPT Pro Web生成 → 3-3 ユーザー確認

#### 3-1. キャラクター定義の作成

シナリオから各登場人物の以下を決定し、`manuscript/character_defs.json` に保存する:
```json
{
  "{キャラA名}": "{キャラA名}: {年齢}{性別}、{髪型}、{髪色}、{体型}、{デフォルト服装の詳細}",
  "{キャラB名}": "{キャラB名}: {年齢}{性別}、{髪型}、{髪色}、{体型}、{デフォルト服装の詳細}",
  "{キャラC名}": "{キャラC名}: {年齢}{性別}、{髪型}、{髪色}、{体型}、{デフォルト服装の詳細}"
}
```

#### 3-1a/3-1b: キャラバリエーション・服装管理

時間経過でキャラの容姿が変わる場合（子供の成長・加齢等）や、場面（シーン）に応じて服装を変える場合の詳細ルール（`outfit_presets` の仕様、CSVでの `outfit_id` 参照方式）は `references/step3-character-variations.md` を参照。該当するストーリーの場合は必ず読み込むこと。

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

#### 3-2-B: 生成実行（ChatGPT Pro Web）

1. 3-2-A のプロンプトをキャラクターごとに `manuscript/characters/prompts/{キャラ名}.txt` として保存する。
2. ChatGPT Pro Web / ChatGPT Images 2.0 / `gpt-image-2` で、各キャラクター画像を生成する。
3. 生成結果を PNG のまま `manuscript/characters/{キャラ名}.png` に保存する。
4. 生成できない場合は `manuscript/characters/character_image_status.md` に `pending_gpt_image2_web` または `blocked_gpt_image2_web` と理由を記録し、次工程へ進まない。

禁止事項:
- OpenAI Images API、APIキー、OpenAI SDK、`client.images.generate/edit` を使わない。
- 旧 `HANDOFF_MODE`、APIハンドオフ、API実行スクリプトを使わない。
- Pillow・ローカル生成・プレースホルダーをキャラクター最終画像として使わない。

#### 3-3. ユーザー確認
- 生成されたキャラクター画像をReadツールで表示する
- ユーザーの承認を得てから次のステップへ進む
- 不満があれば外見設定を修正して再生成する

---

### Step 4: コマ割りCSV作成

**重要: 既存の `generate_comicle_csv.py` は使用しない。Claude自身がCSVを直接生成する。**

シナリオ + キャラクター定義 + 作画設定をもとに、コミクル用CSV（`panels/comicle_output.csv`）を生成する。詳細仕様（CSVヘッダーと列仕様、コマ別テキストJSONのスキーマ、7種類のコマ割りテンプレート、コマ読み順、各ページのプロンプト構造、原文テキストの活用ルール、CSV生成時の注意事項、前付けページ、コラムページ、テンプレート選択の目安）は `references/step4-csv-spec.md` を参照。Step 4 を実行する際は必ず読み込むこと。

要点のみ:
- ヘッダーは5列: `ページ番号,使用するコマ割りテンプレ,漫画作成のプロンプト,コマ別テキストJSON,outfit_id`
- コマ割りテンプレートは7種類（テンプレ1〜7）、読み順は日本の漫画形式（右上から左下へ）
- セリフ「」は全て省略せずCSVに含め、原稿カバー率80%以上を目指す
- `コマ別テキストJSON` は画像生成プロンプトには渡さず、後工程のBlind-OCR比較専用（confirmation bias排除のため意図的に分離）

#### ユーザー確認
- CSV生成後、以下を表示して確認を得る:
  - 総ページ数
  - テンプレート分布（各テンプレの使用割合）
  - 最初の3ページ、中盤の1ページ、最後の1ページのプロンプトサンプル

### Step 5: 画像生成（ChatGPT Pro Web + QCループ）

ChatGPT Pro Web / ChatGPT Images 2.0 / `gpt-image-2` でページ画像を生成し、Blind-OCR・Vision-check・目視確認で品質を確認する。詳細仕様（パラメータ、ループフロー疑似コード、処理の流れ、成果物ファイル命名、進捗管理JSON、生成量の目安、Step4/Step6との接続関係）は `references/step5-image-generation.md` を参照。判定モジュール自体（OCR/Vision-checkの設計原則・プロンプト・比較ロジック）は `references/step5-qc.md` を参照。Step 5 を実行する際は両方を必ず読み込むこと。

要点のみ:
- 画像生成はChatGPT Pro Webのみ。OpenAI Images API・APIキー・SDK直接実行・旧`openai-image-gen`は使わない
- Pillow合成・ローカル生成・プレースホルダーを最終ページとして使わない
- `max_iter`（既定3）までQC不合格ページをWeb再生成し、超過分は `blocked_gpt_image2_web` として止める
- テキストページ（`コマ別テキストJSON == []`）は画像生成自体をスキップし自動PASS

---

### Step 5-QC: Blind-OCR + Vision-check 判定モジュール

Step 5 の画像生成ループ内で使用する品質判定モジュール。詳細仕様（confirmation bias排除の設計原則、OCRプロンプトテンプレート、正規化・比較ロジック、PASS/FAIL判定条件、FAIL時のフィードバック注入フォーマット、エラーハンドリング、Vision-checkのプロンプトテンプレートとキャラ名抽出ロジック、OCR×Vision-check統合判定表）は `references/step5-qc.md` を参照。Step 5 のループを実装・実行する際は必ず読み込むこと。

要点のみ:
- OCRは期待テキストを一切見せず「画像→テキスト抽出」のみ行い、比較はプログラム側（Python）で正規化後に完全一致で判定する（fuzzy matching禁止）
- Vision-checkはキャラごとに1人ずつYES/NOで存在確認する（confirmation bias排除のため一括質問しない）
- ページ判定はOCR・Vision-checkの両方がPASSして初めて確定する（片方でもFAILならページFAIL→再生成）
- テキストページ（`コマ別テキストJSON == []`）は画像生成・OCR・Vision-check全てスキップし自動PASS

### Step 5.5: 廃止済みフォールバック

Step 5.5 の Pillow 合成フォールバックは廃止済み。現在の ebook-to-manga では使用しない。

- Pillow・ローカル手続き生成・プレースホルダー画像を最終ページとして使わない。
- OpenAI Images API、APIキー、SDK直接実行、旧 API ハンドオフを使わない。
- Step 5 で max_iter を超えたページは `blocked_gpt_image2_web` として止め、最終プロンプト・参照画像・失敗理由を保存する。
- blocked ページが残っている場合は Step 7 の EPUB 製本へ進まない。

---

### Step 6: 表紙作成

マンガ版の書籍表紙を生成する。

> **現行フロー**
> - 6-A プロンプト構築 → 6-B ChatGPT Pro Web / `gpt-image-2` 生成 → 6-C 保存・ユーザー確認

#### 6-A: 表紙プロンプト構築（共通）

以下の手順でプロンプトを組み立てる（モード共通）。

#### 表紙プロンプトの構成

既存の `表紙プロンプト.md` の5ステップ構造（description / design_taste / buzz_elements / character / processing_steps のYAML構成）をベースに、マンガ用に適応する。プロンプト全文テンプレートは `references/step6-cover-prompt.md` を参照。Step 6 を実行する際は必ず読み込むこと。

#### 6-B: 生成実行（ChatGPT Pro Web）

1. 表紙プロンプトを `KDP出版用/cover_prompt.txt` に保存する。
2. 主人公キャラの参照PNGを確認し、ChatGPT Pro Web / ChatGPT Images 2.0 / `gpt-image-2` に添付して生成する。
3. 生成結果を PNG のまま `KDP出版用/cover.png` に保存する。
4. OpenAI Images API、APIキー、SDK直接実行、旧APIハンドオフ、Pillow変換による最終表紙作成は使わない。
5. 生成できない場合は `KDP出版用/cover_status.md` に `blocked_gpt_image2_web` と理由を記録し、表紙完成扱いにしない。

#### ユーザー確認
- 表紙画像をReadツールで表示して確認を得る
- サムネイル縮小表示（幅100px相当）を想定してタイトル・帯風キャッチコピーが判読できるかを確認し、読めなければ文字を大きくして再生成する
- 不満があればプロンプトを修正して再生成する

---

### Step 7: 製本（EPUB化）

固定レイアウトEPUB3をPythonで直接構築する（Pandocでは固定レイアウトEPUBを生成できないため`zipfile`モジュールを使用）。EPUB構造、テキストページの扱い、EPUB生成スクリプト全文、EPUB仕様、Step5ハイブリッドQCとの下流互換性の詳細は `references/step7-epub-build.md` を参照。Step 7 を実行する際は必ず読み込むこと。

要点のみ:
- ビューポート `1080x1920`（9:16）、`rendition:layout: pre-paginated`、`page-progression-direction: ltr`
- ページ画像は `panels/pages/page_{NNN}.png` を `glob` で収集（中間ファイル `_iter_*.png` は自動除外）
- **前提**: Step 5 完了かつ `blocked_pages` が空であることを確認してから実行する

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

書籍テーマに応じて、20ジャンル（恋愛ドラマ／異世界バトルもの／ミステリー／ビジネス／哲学思想／解説教育／ホラー／スポーツ／SF・宇宙／日常コメディ／時代劇・歴史／サスペンス・スリラー／ファンタジー・冒険／グルメ・料理／青春・学園／サイバーパンク／投資／副業／趣味／論文・学術）から最適な作画設定（作画スタイル・色調・線画・演出）を自動選択する。

ジャンル別の設定全文は `references/genre-master.md` を参照。Step 1（ジャンル自動判定）、Step 3（キャラデザ）、Step 4（CSVプロンプトの◆【作画】欄）、Step 6（表紙）で、選択したジャンルの設定全文をそのまま埋め込む。

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

## コスト見積もり

本スキルは OpenAI Images API を使わないため API単価ベースのコスト試算は行わない。ChatGPT Pro Web の契約範囲内で生成し、費用ではなく生成量を管理する。

| 項目 | 100ページの場合の目安 |
|------|----------------------|
| Step 5: ページ画像 | 100枚 + QC不合格分のWeb再生成 |
| Step 3: キャラリファレンス | 2-3枚 |
| Step 6: 表紙 | 1枚 |
| blocked管理 | `blocked_gpt_image2_web` ページはEPUB化前に解消必須 |

---

## エラーハンドリング

| エラー | 対処 |
|--------|------|
| ソースフォルダが見つからない | エラー表示し、利用可能なebookフォルダを一覧する |
| ChatGPT Pro Webで生成できない | APIへ切り替えず、該当画像を `blocked_gpt_image2_web` としてプロンプト・参照素材・理由を保存する |
| 画像生成失敗 | 失敗ページをログに記録し、ChatGPT Pro Webで再生成する。max_iter超過時は `blocked_gpt_image2_web` とする |
| EPUB構築エラー | エラー詳細を表示し、画像ファイルの存在を確認 |
| ページ数超過 | Step 2のシナリオを凝縮して再生成 |
| キャラ外見の不一致 | キャラ定義の詳細を強化してプロンプトを再生成 |

## 注意事項

- Windows環境では `python3` ではなく `python` を使用する
- 100枚の画像生成は時間がかかるため、10枚程度を1作業単位として進める。APIレート制限対策ではなく、ChatGPT Pro Web側の生成可否と保存漏れを確認する
- 生成画像の品質にはばらつきがある。QC不合格ページはWeb再生成し、ローカル合成で代替しない
- 固定レイアウトEPUBはKindle Unlimitedの対象外となる場合がある（KDPの最新規約を確認）。EPUBの表示確認はKindleプレビューアで必ず行うこと

---

## E2E動作確認手順

Step 4/Step 5 のハイブリッドQCパイプラインを新規実装・改修した場合の動作確認手順（CSV生成確認、OCR判定確認、フィードバック注入確認、blocked管理確認、progress.json確認、下流工程非破壊確認、Vision-check単体動作確認、OCR×Vision-check独立性確認、テキストページ自動スキップ確認、合格基準）は `references/e2e-verification.md` を参照。通常のマンガ化実行では読む必要はない。
