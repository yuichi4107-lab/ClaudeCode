## Step 5-QC: Blind-OCR + Vision-check 判定モジュール

> `ebook-to-manga` SKILL.md の Step 5 から参照される詳細仕様ファイル。Step 5 の画像生成ループを組む際は本ファイルを読み込むこと。

Step 5 の画像生成ループ内で使用する OCR 品質判定の仕様。
工程5（Step 5 ループ全面改修）でこのサブセクションを参照してループを組む。

### 設計原則: Confirmation Bias 排除（最重要）

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

### OCR 対象と対象外

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
コマ領域ごとにクロップして個別 OCR するのではなく、ページ全体画像を1回の API 呼び出しで処理する。
OCR モデルはページ全体から各吹き出しを自動検出し、`panel_id` と `type` を推定する。
### OCR プロンプトテンプレート

モデル: テキスト読み取り可能なVision/OCRモデル（画像生成モデルは使用しない）
temperature: `0.0`（決定論的出力）
response_format: `{"type": "json_object"}`（JSON 以外の出力を防ぐ）
max_tokens: `4096`

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

### 比較ロジック（決定論的）

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

### PASS/FAIL 判定条件

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

### エラーハンドリング

**OCR API エラー・空レスポンス時:**
- OCR 呼び出しは最大 **2回リトライ**（合計3回試行）する
- リトライ間隔: 1秒
- 3回すべて失敗した場合は `{"bubbles": []}` を返す（空バブル扱い）
- 空バブルは比較時に「検出テキストなし」として全エントリが FAIL になる
- つまり OCR 失敗は自動的に FAIL 扱いとなり、次のWeb再生成 iter または `blocked_gpt_image2_web` に進む

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

### OCR と Vision-check の統合判定

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

### Vision-check: キャラ存在検証の設計原則

**目的**: 画像生成ループ内でキャラ欠落バグ（例: page_002 山田課長省略事象）を自動検出し、
再生成トリガーをかけることで全キャラが正しく描画された画像を確定する。

**confirmation bias 排除方針**:
- OCR の反面教師（期待テキストをプロンプトに含める設計）とは異なり、
  Vision-check は「このキャラクターが存在するか」を1人ずつ YES/NO で問う。
- 「全員が存在するか」をまとめて問うと、モデルが期待値に引っ張られて過剰に YES を返す
  確証バイアスが発生する恐れがある。キャラごとに個別質問することで判定精度を高める。
- システムプロンプトで「テキスト枠・名前ラベルのみの場合は NO とする」と明示し、
  「文字でキャラ名が書かれている」と「イラストが描かれている」の混同を防ぐ。

### 対象ページ

**Vision-check を実行するページ:**
- `コマ別テキストJSON` が空配列 `[]` かつ画像生成が実行されたページ（セリフなしページ。例: 登場人物紹介ページ）
- `コマ別テキストJSON` に1件以上のエントリがあるページ（セリフありページ）

つまり、**画像生成が発生したすべてのページ**が Vision-check の対象となる。

**Vision-check をスキップするページ:**
- テキストページ（`コマ別テキストJSON` が `[]` かつ Step 5 で画像生成自体をスキップ済みのページ）
  - これらは画像ファイルが存在しないため Vision-check の対象外とする

### キャラ名抽出ロジック

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

### Vision-check プロンプトテンプレート

モデル: `gpt-4o`（vision 機能）
temperature: `0.0`（決定論的出力）
response_format: `{"type": "json_object"}`

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

**Vision-check 指示文:**

```text
あなたは画像品質チェッカーです。与えられたマンガ画像を分析し、指定されたキャラクターが全身イラストとして描かれているかを1人ずつ YES または NO で判定してください。
テキスト枠・名前ラベルのみでキャラクターのイラスト本体が存在しない場合は NO としてください。
イラストが実際に画像内に描かれているかを画像の内容から判断してください。必ず JSON で返してください。

確認対象:
- {キャラ名}（{appearance}）

出力形式（JSONのみ。説明文禁止）:
{"vision_checks": [{"char_name": "ミサキ", "result": "YES", "reason": "..."}]}
```

**レスポンス JSON スキーマ:**
```json
{
  "vision_checks": [
    {"char_name": "ミサキ", "result": "YES", "reason": "1段目に全身イラストあり"},
    {"char_name": "山田課長", "result": "NO", "reason": "テキスト枠のみ、イラストなし"}
  ]
}
```

### 判定ロジック

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

### エラーハンドリング

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
