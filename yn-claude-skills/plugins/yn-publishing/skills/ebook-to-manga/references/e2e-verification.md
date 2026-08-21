# E2E動作確認手順

> `ebook-to-manga` SKILL.md の末尾から参照される詳細仕様ファイル。Step 4/Step 5 のハイブリッドQCパイプラインを新規実装・改修した際の動作確認手順。通常のマンガ化実行では読む必要はない。

## 目的

ハイブリッドQCパイプライン（工程1〜5の本実装成果）が実データで期待通り動作することを確認する。
Step 4 の `コマ別テキストJSON` → Step 5 の Blind-OCR 判定 → Web再生成または `blocked_gpt_image2_web`
という一連のデータフローが途切れなく機能していることを担保する。

---

## 確認項目

### 1. CSV生成確認（Step 4）

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

### 2. OCR判定確認（Step 5 / Step 5-QC）

Step 5 の Blind-OCR が正しく動作していることを確認する。

**確認ステップ:**

1. 生成済みページ画像（例: `pages/page_039_iter_1.png`）を使って Step 5-QC の OCR プロンプトを単体実行する
2. レスポンスが `{"bubbles": [...]}` の JSON 形式で返ること
3. OCR 結果の `detected_text` が CSV の `text` フィールドと一致（または不一致）することを確認する

**重要チェック**: プロンプトに期待テキスト（CSV の `text` フィールド値）が含まれていないこと（confirmation bias 排除）。

**確認時の注意:**
- APIキーやSDKコード例を使わない。
- OCR結果は `quality-check.md` または `progress.json` に要約して保存する。
- OCRが実行できない場合は、該当ページを手動レビュー対象にする。

---

### 3. フィードバック注入確認（Step 5 FAIL 時）

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

### 4. blocked管理確認

**確認ステップ:**

1. `max_iter` を一時的に `1` に設定して難ページ（例: ページ39）を単体実行する
   ```python
   # Step 5 のループ引数で max_iter=1 を指定
   max_iter = 1
   ```
2. iter=1 が FAIL した場合、以下が記録されることを確認する:
   - `pages/page_039_iter_1.png`（監査用。iter=1 のWeb生成画像）
   - `prompts/page_039_blocked_prompt.txt`（再生成用プロンプト）
   - `progress.json` の `blocked_pages` と `blocked_reasons`
3. `pages/page_039.png` が存在しない状態で Step 7 に進まないことを確認する

**目視確認ポイント:**
- blockedページが最終画像として混入していないこと
- Web再生成に必要なプロンプトと参照画像が保存されていること

---

### 5. progress.json確認

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
  "status": "blocked_gpt_image2_web",
  "completed": 99,
  "total": 100,
  "failed": [39],
  "blocked_pages": [39],
  "blocked_reasons": {"39": "ocr_fail"}
}
```

- `blocked_pages` リストに停止ページが記録されていること
- blockedページが残っている場合は Step 7 に進まないこと

---

### 6. 下流工程非破壊確認（Step 6 / Step 7 / Step 8）

ハイブリッドQCループの追加が Step 6 以降に影響を与えないことを確認する。

**Step 6（表紙作成）:**
- Step 6 は `pages/` フォルダを参照しないため影響なし
- `KDP出版用/cover.png` がChatGPT Pro Web / `gpt-image-2`で生成されていることを確認する

**Step 7（EPUB製本）:**
- `panels/pages/page_{NNN}.png`（3桁ゼロ埋め）ファイルが全ページ分存在することを確認する
- `blocked_pages` が空であることを確認する
- `_iter_*.png` 等の中間ファイルは `page_*.png` のワイルドカードには一致しないため自動的に除外される
- EPUB 生成スクリプトが `glob("page_*.png")` で正しい枚数を収集できることを確認する

**Step 8（メタデータ）:**
- Step 8 は画像ファイルを参照しないため影響なし
- `KDP出版用/書籍情報.md` / `ジャンル・キーワード.md` / `書籍紹介文_HTML.html` が正常生成されることを確認する

---

### 7. Vision-check 単体動作確認

**確認ステップ:**

1. セリフなしページ（例: page_002 登場人物紹介ページ）を対象として、キャラを1人意図的に欠落させた画像を用意する
   - 欠落させ方: 例えば山田課長の画像スロットを空欄またはテキスト枠のみにした画像を用意する
2. Vision-check を単体実行して `vision_check()` 関数を呼び出す
3. Vision-check が FAIL を返し、`missing_chars` に欠落キャラ名が含まれることを確認する
4. Step 5 のループで再生成がトリガーされることをログで確認する
   - 期待ログ: `[vision] FAIL: page=002 missing=[山田課長]`
   - 期待ログ: `[iter 2] 再生成開始（Vision-check FAIL: missing=[山田課長]）`

---

### 8. OCR × Vision-check 独立性確認

**確認ステップ:**

1. セリフありページを1件選び、OCR は PASS するが Vision-check は FAIL になる人工ケースを作成する
   - 例: テキストが正確に描かれているがキャラの1人がテキスト枠のみで描かれていない画像を用意する
2. Step 5 のループで OCR 判定 → Vision-check 判定を順に実行する
3. OCR PASS / Vision-check FAIL のケースでも**ページ全体が FAIL** 判定になることを確認する
   - 期待ログ: `[ocr] iter_1 result=PASS`、`[vision] FAIL: page={NNN} missing=[...]`
   - 期待ログ: `[iter 1] ページ判定: FAIL（OCR=PASS, Vision=FAIL）→ 再生成`

---

### 9. テキストページの自動スキップ確認

**確認ステップ:**

1. `コマ別テキストJSON` が `[]` のテキストページ（画像生成スキップ対象）を指定して Step 5 を実行する
2. 画像生成・OCR・Vision-check すべてがスキップされ、自動 PASS として `progress.json` に記録されることを確認する
   - 期待ログ: `[skip] page={NNN}: テキストページ（画像生成スキップ済み）→ 自動 PASS`

---

## 合格基準

以下をすべて満たした場合に E2E 確認完了とする。

| 確認項目 | 合格条件 |
|---|---|
| CSV生成 | `コマ別テキストJSON` 列が全ページで有効な JSON（または空配列） |
| OCR判定 | Blind-OCR が期待テキストなしで正しく読み取り PASS/FAIL を判定 |
| フィードバック注入 | FAIL 時に `◆【前回失敗・最重要】` セクションが次 iter のプロンプトに含まれる |
| blocked管理 | max_iter 超過時に `blocked_pages` / `blocked_reasons` が記録され、EPUB Step 7 に進まない |
| progress.json | `blocked_pages` / `blocked_reasons` / `vision_check_failed_pages` が記録され、EPUB Step 7 で参照可能な状態 |
| ファイル命名 | 全ページが `pages/page_{NNN}.png` として揃っている（中間ファイルは除外） |
| EPUB生成 | Step 7 が変更なく動作し、正常な EPUB が出力される |
| KDPメタデータ | Step 8 が変更なく動作し、書籍情報・紹介文が出力される |
| 日本語テキスト | 全ページのセリフ・ナレーションが Blind-OCR PASS または手動レビューPASS |
| Vision-check 単体動作 | セリフなしページでキャラ欠落を Vision-check が FAIL 検出し再生成ループが発動する |
| OCR × Vision-check 独立性 | OCR PASS / Vision-check FAIL のケースでもページ全体が FAIL 判定になる |
| テキストページスキップ | `コマ別テキストJSON == []` のページで OCR・Vision-check 両方スキップ・自動 PASS になる |
