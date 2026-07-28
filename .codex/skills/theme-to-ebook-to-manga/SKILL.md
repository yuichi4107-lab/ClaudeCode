---
name: theme-to-ebook-to-manga
description: テーマまたは添付素材から、まず theme-to-ebook で文字中心のKindle電子書籍を作成し、その完成済みソースを ebook-to-manga に渡してマンガ版EPUB・KDPメタデータまで一気通貫で作成する親オーケストレーションスキル。初回は選択式＋自由記述で電子書籍条件とマンガ化条件を確認し、画像生成はAPIを使わずChatGPT Images 2.0（Codex/ChatGPT側の画像生成経路）で行う。
---

# Theme-to-Ebook-to-Manga

テーマまたは添付素材から、文字中心電子書籍とマンガ版を連続制作する親スキル。

このスキル自体は本文生成やマンガ画像生成の詳細を再実装しない。前半は `theme-to-ebook`、後半は `ebook-to-manga` を使い、両者の接続条件と品質ゲートを管理する。

## 役割

- 文字中心電子書籍を `theme-to-ebook` で作る
- `theme-to-ebook` の出力を `ebook-to-manga` の入力として検査する
- 検査に通ったら `ebook-to-manga` でマンガ化する
- 文字本とマンガ版の成果物パス、進捗、品質チェック結果を一つの進行記録にまとめる

## 最優先ルール

- 画像生成にAPIを使わない
- `OPENAI_API_KEY`、OpenAI API、`openai-image-gen`、`client.images.generate`、`client.images.edit` は使わない
- ChatGPT Images 2.0（Codex/ChatGPT側の画像生成経路）で生成する
- `.company/codex/queue/` へのジョブ引き渡しは作らず、このCodexセッション内で生成・保存・QC・EPUB反映まで進める
- `ebook-from-theme` は使わない。このスキルでは `theme-to-ebook` を文字中心電子書籍制作の正本として使う

## 二本立て出版モード

ユーザーが「文字版と漫画版」「完全文字版と完全漫画版」「自分史の二本立て」と言った場合は、以下を標準にする。

- 文字版は漫画ページを含まない完全文字版として作る
- 文字版の中に章末漫画、漫画風ストーリーパネル、漫画パートを混ぜない
- 漫画版は文字版のおまけではなく、独立したフル漫画版として作る
- 文字版の承認または品質チェック完了後に、承認済みソースだけを漫画化する
- `progress.json` または `PIPELINE_REPORT.md` に `edition_policy.text_edition = complete_text_only` と `manga_edition = full_manga` を記録する
- 自分史など個人情報を含む案件では、実名、写真、地名、会社名、家族関係の公開範囲を漫画化前に確認する

## 入力

- **テーマまたは添付素材**: テーマ文、文字起こし、メモ、既存原稿など
- **文字中心電子書籍の条件**: `theme-to-ebook` のPhase 0回答
- **マンガ化条件**: ページ数、作画方向、章末/章頭配置など
- **著者名・出力名**: 任意。未指定なら既存スキルのルールで自動決定する

## Phase 0: 統合初回質問

開始時に、文字本とマンガ化の条件をクリック式選択UIで確認する。`request_user_input` が使える場合はその選択カードを使う。使えない場合は `.company/scripts/ebook_setup_ui.py` のローカルクリック式フォームを起動する。Markdownの表や `1A、2B...` 形式を標準にしない。

**クリック式UIの出し方:**

1回目の `request_user_input`:

- `theme_handling`: テーマの扱い
  - 入力内容のテーマで進める (Recommended)
  - 入力内容を少し広げて進める
  - 入力内容を絞り込んで進める
- `target_reader`: 想定読者
  - 初心者・これから始める人 (Recommended)
  - 中小企業の経営者・管理職
  - 実務担当者・現場リーダー
- `book_type`: 文字本の型
  - 実践書・手順書 (Recommended)
  - やさしい入門書
  - ストーリー・事例中心

2回目の `request_user_input`:

- `text_length`: 文字本の文字量
  - 約100,000字 (Recommended)
  - 約50,000字
  - 約25,000字
- `manga_pages`: マンガ版の目標ページ数
  - 100ページ前後 (Recommended)
  - 60ページ前後
  - 120ページ前後
- `manga_structure`: マンガの配置・構成
  - 文字本をもとに独立したマンガ版を作る (Recommended)
  - 章ごとにマンガパートを作る
  - 重要事例だけマンガ化する

3回目の `request_user_input`:

- `manga_style`: 作画方向
  - 日本のビジネスマンガ調 (Recommended)
  - やさしい学習マンガ調
  - 少しドラマ寄り

回答が不足している場合は、不足項目だけクリック式UIで短く再質問する。「お任せ」「推奨で」「デフォルトで」の場合は推奨値を採用する。自由記述はUI側の `Other` またはクリック回答後の短い補足確認で受け取り、選択肢より優先する。ユーザーに `1A、2B...` のような長いコード型回答を要求しない。

**ローカルフォームの出し方（`request_user_input` が使えない場合）:**

```bash
python3 .company/scripts/ebook_setup_ui.py --theme "{テーマ}" --mode theme-to-ebook-to-manga
```

保存先は `.company/outputs/ebook-setup-inputs/latest.json`。回答を読み取り、`PIPELINE_REPORT.md` や各 `progress.json` の Phase 0回答へ反映する。

## Phase 1: theme-to-ebook 実行

Phase 0のうち、文字中心電子書籍に関係する回答を `theme-to-ebook` に渡して実行する。

`theme-to-ebook` 側で必ず行うこと:

- 初回質問の回答を `progress.json` に保存する
- Step 0 のテーマリサーチを実行する
- `project.md` を作る
- `manuscript/` に7ファイルを作る
- 文字版ポリシーに従い、漫画ページを混ぜずに本文と表紙を作る
- `KDP出版用/` にメタデータと表紙を作る
- 最終品質チェックで85点以上を満たす

出力先:

```text
.company/outputs/ebooks/{book-name}/
```

## Phase 2: 接続前チェック

`ebook-to-manga` に渡す前に、文字本ソースフォルダを検査する。

必須チェック:

- `project.md` が存在する
- `manuscript/` が存在する
- `manuscript/` に、はじめに・第1章〜第5章・おわりに相当のMarkdownが揃っている
- `progress.json` が存在し、`theme-to-ebook` の主要Stepが完了している
- `_research/theme_research.md` が存在する
- `KDP出版用/` に文字本用メタデータがある
- 本文画像リンクがある場合、リンク先ファイルが存在する
- 文字本の品質チェックが85点以上、または改善ループ済みで許容理由が記録されている

不足がある場合:

- 原則として `ebook-to-manga` へ進まない
- 不足が `theme-to-ebook` 側で補える場合は、Phase 1へ戻って補修する
- 補修不能な場合は `handoff_to_manga_blocked.md` を文字本フォルダ直下に作り、何が足りないかを記録する

## Phase 3: ebook-to-manga 実行

Phase 2に通ったら、文字本の出力フォルダを `ebook-to-manga` のソースフォルダとして渡す。

### マンガ版タイトル命名ルール

マンガ版のタイトルは必ず以下にする。

```text
マンガでわかる！{文字中心電子書籍のタイトル}
```

例:

```text
文字中心電子書籍: AIが勝手に仕事する会社の作り方
マンガ版: マンガでわかる！AIが勝手に仕事する会社の作り方
```

このタイトルは、マンガ版の `project.md`、EPUBファイル名、表紙、`KDP出版用/書籍情報.md`、`ジャンル・キーワード.md`、`書籍紹介文_HTML.html`、`PIPELINE_REPORT.md` に反映する。サブタイトルは文字中心版のサブタイトルを流用してよいが、タイトル本体には必ず `マンガでわかる！` を付ける。

```text
source_folder = .company/outputs/ebooks/{book-name}/
manga_title = マンガでわかる！{文字中心電子書籍のタイトル}
target_pages = Phase 0 項目5の回答
genre = Phase 0 項目7の回答、または ebook-to-manga の自動判定
```

`ebook-to-manga` 側で実行する標準順序:

1. Step 1: ソース分析と準備
2. Step 2: マンガ用シナリオ作成
3. Step 3: キャラクターデザイン
4. Step 4: コマ割りCSV作成
5. Step 5: ChatGPT Images 2.0直生成でページ画像作成
6. Step 6: 表紙作成
7. Step 7: EPUB製本
8. Step 8: KDPメタデータ作成

## Phase 4: 統合品質チェック

文字本とマンガ版の両方について、最終確認を行う。

文字本:

- `project.md`
- `manuscript/`
- `KDP出版用/` のメタデータ
- 表紙PNG/JPEG
- EPUBがある場合はEPUB構造

マンガ版:

- `manuscript/シナリオ.txt`
- `manuscript/character_defs.json`
- `panels/comicle_output.csv`
- `pages/` または分冊ごとの `pages/`
- `KDP出版用/` のEPUB、表紙、メタデータ
- 画像生成がAPI不使用で行われた記録

統合レポート:

```text
.company/outputs/ebooks-manga/{book-name}/PIPELINE_REPORT.md
```

レポートには以下を含める:

- 入力テーマ
- Phase 0回答
- 文字本ソースフォルダ
- マンガ版出力フォルダ
- 文字中心電子書籍タイトル
- マンガ版タイトル
- 文字本の品質スコア
- マンガ版の品質スコア
- 生成画像数
- API不使用の確認
- Kindle Previewerで未確認の場合の残課題

## 完了条件

- 文字中心電子書籍の成果物が `.company/outputs/ebooks/{book-name}/` に揃っている
- マンガ版の成果物が `.company/outputs/ebooks-manga/{book-name}/` に揃っている
- マンガ版タイトルが `マンガでわかる！{文字中心電子書籍のタイトル}` になっている
- 文字本からマンガ版へ進む接続前チェックが記録されている
- `PIPELINE_REPORT.md` が作成されている
- 画像生成にAPIを使っていないことが記録されている

## 使い分け

- 文字本だけ作る場合は `theme-to-ebook`
- 既存文字本をマンガ化するだけなら `ebook-to-manga`
- テーマから文字本を作り、そのままマンガ版まで作る場合はこの `theme-to-ebook-to-manga`
