## Step 5: 画像生成（ChatGPT Pro Web + QCループ）

> `ebook-to-manga` SKILL.md の Step 5 から参照される詳細仕様ファイル。Step 5 を実行する際は本ファイルを読み込むこと。OCR/Vision-checkの判定モジュール自体の仕様は `references/step5-qc.md` を参照。

### 概要

ChatGPT Pro Web / ChatGPT Images 2.0 / `gpt-image-2` でページ画像を生成し、
Blind-OCR・Vision-check・目視確認で品質を確認する。

- 画像生成は ChatGPT Pro Web のみ。
- OpenAI Images API、APIキー、SDK直接実行、旧 `openai-image-gen` は使わない。
- Pillow合成・ローカル生成・プレースホルダーを最終ページとして使わない。
- QCで不合格のページは、フィードバックを追記して ChatGPT Pro Web で再生成する。
- 再生成できない場合は、該当ページを `blocked_gpt_image2_web` として止める。

### パラメータ

| パラメータ | 既定値 | 説明 |
|---|---|---|
| `max_iter` | `3` | FAIL 判定でWeb再生成する上限 |
| バッチサイズ | `10` | 1回の作業単位。Web生成の実運用に合わせて調整する |
| 保存形式 | PNG（無損失） | 生成結果をPNGのまま保存する |

`max_iter` の調整目安:
- 高精度が必要な場合: `3` のまま
- 処理速度優先の場合: `1` も可。ただし不合格ページを最終ページとして通さない

### ループフロー（疑似コード）

```
CSV を読み込み、全ページリストを取得する
char_defs = load_json("manuscript/characters/character_defs.json")

for page in pages:
    if page の コマ別テキストJSON == []:
        画像生成をスキップ（テキストページは生成不要）
        PASS として記録 → 次ページへ

    current_prompt = 元の画像生成プロンプト
    converged = False
    page_chars = extract_page_chars(page.prompt, char_defs)

    for iter in range(1, max_iter + 1):
        ChatGPT Pro Web / gpt-image-2 で画像を生成し pages/page_{NNN}_iter_{iter}.png に保存

        ocr_verdict = blind_ocr_and_compare(pages/page_{NNN}_iter_{iter}.png, コマ別テキストJSON)
        vision_verdict, missing_chars = vision_check(pages/page_{NNN}_iter_{iter}.png, page_chars)

        if ocr_verdict == PASS and vision_verdict == PASS:
            pages/page_{NNN}_iter_{iter}.png を pages/page_{NNN}.png としてコピー
            converged = True
            progress.json を更新（このページ完了）
            break

        current_prompt = build_feedback_prompt(元のプロンプト, ocr_verdict, vision_verdict, missing_chars)

    if not converged:
        prompts/page_{NNN}_blocked_prompt.txt に最終プロンプトを保存
        progress.json を blocked_gpt_image2_web と理由付きで更新
        このページを最終成果物にしない

各バッチ完了後に progress.json を更新する
```

### 処理の流れ（詳細）

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
- `SIZE`: `"1024x1536"`（9:16縦長）
- `FILE_PREFIX`: `page_{ページ番号3桁ゼロ埋め}_iter_{iter}` （例: `page_039_iter_1`）
- **保存形式**: PNG（`.png`）。ChatGPT Pro Webから取得した画像をそのまま保存する
- **モデル名**: `gpt-image-2`（ChatGPT Pro Web / ChatGPT Images 2.0）
- **参照画像**: プロンプト内の `添付の([^\s、,]+?\.png)` から抽出したキャラクターリファレンス PNG をWeb生成時に添付する
- **プロンプト保存**: 各iterのプロンプトを `prompts/page_{NNN}_iter_{iter}.txt` に保存する

**4. Blind-OCR 判定（→ Step 5-QC 参照）**

生成した `pages/page_{NNN}_iter_{iter}.png` を `### Step 5-QC` の仕様に従って OCR する。
OCR は `gpt-4o`（openai、temperature=0.0）で実行し、期待テキストは一切渡さない。
セリフなしページ（`コマ別テキストJSON == []`）は OCR をスキップし、自動 PASS 扱いとする。

**5. Vision-check 判定（→ Step 5-QC 参照）**

`### Step 5-QC` の「Vision-check」仕様に従い、`pages/page_{NNN}_iter_{iter}.png` に対して
gpt-4o vision でキャラ存在チェックを実行する。
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
最終プロンプト、失敗理由、参照画像を保存し、Pillow合成やローカル代替画像で完了扱いにしない。

### 成果物ファイル命名

| ファイル名パターン | 生成タイミング | EPUB 向け扱い |
|---|---|---|
| `pages/page_{NNN}_iter_{N}.png` | 各 iter のWeb生成画像 | 監査用。PASS した iter の画像のみ `page_{NNN}.png` にコピーされる |
| `pages/page_{NNN}.png` | PASSしたページの最終画像 | Step 7 EPUB 製本が直接参照する |
| `prompts/page_{NNN}_blocked_prompt.txt` | max_iter 超過時 | 再生成用。EPUBには入れない |

> **EPUB製本（Step 7）との整合**: Step 7 は `pages/page_{NNN}.png` だけを収集する。
> `blocked_gpt_image2_web` ページが残っている場合は Step 7 に進まない。

### 進捗管理

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

### 生成量の目安

API単価ベースのコスト試算はしない。ChatGPT Pro Webの契約範囲で生成する。

| 項目 | 100ページの場合の目安 |
|---|---|
| ページ画像 | 100枚 + QC不合格分のWeb再生成 |
| Blind-OCR / Vision-check | 必要なページのみ実施 |
| blocked管理 | `blocked_pages` が空になるまでEPUB化しない |

**max_iter 変更時の管理方針:**

| max_iter | 方針 |
|---|---|
| 1 | 速度優先。FAILページはすぐ `blocked_gpt_image2_web` 候補になる |
| 2 | バランス型 |
| **3（既定）** | 品質優先。Web再生成を最大3回まで試す |
| 4以上 | 原則使わない。時間が伸びるため、プロンプト改善を優先する |

### 維持される Step 4 と Step 6 の仕様

**Step 4 との接続（上流）:**
- Step 4 で生成した CSV（`panels/comicle_output.csv`）の `コマ別テキストJSON` 列が
  本ループの OCR 比較と手動レビューの期待テキスト源になる
- 使用するコマ割りテンプレは Step 4 の CSV `使用するコマ割りテンプレ` 列から取得する（7種）
- キャラクターリファレンス画像（`character_defs.json`）は Step 3 の成果物を引き続き使用する

**Step 6 との接続（下流）:**
- 本ステップ完了後、全ページが `pages/page_{NNN}.png` として揃っており、`blocked_pages` が空であること
- Step 6（カバー画像生成）はこのファイル群を参照しないため影響なし
- Step 7（EPUB製本）は `pages/page_{NNN}.png` を収集するため、命名規則の一貫性が保証されていれば修正不要

---

