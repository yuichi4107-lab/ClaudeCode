# セリフ比較分析チェックリスト

compare_dialogues.pyの出力結果を解釈するためのチェックリスト。

## 必須確認項目（問題があれば修正が必要）

### 1. セリフ反映率
- **合格基準**: 150/150件（100%）
- **不合格時の対処**: generate_comicle_csv.pyの入力CSVカラム名を確認する（`type`, `character`, `text`形式が必要）

### 2. セリフ行数の一致
- **合格基準**: script側とcomicle側が完全一致
- **不合格時の対処**: generate_comicle_csv.pyのセリフ結合ロジックを確認する

### 3. 30字超えセリフ数
- **合格基準**: 0件（和歌・引用文を除く）
- **不合格時の対処**: convert_to_csv.pyの分割閾値（デフォルト30字）を確認し、台本Markdownを修正する

## 改善推奨項盾(必須ではないが品質向おに感能）

### 4. 感情コード分布
- **現状**: N（通常）が98%以上を占もり傾向がある
- **改善方法**: generate_comicle_csv.pyの感情推定ロゲックに追加カーワードを登課する
  - 悲しみ（S）: 「悲しい」「辛い」「亡くなった」「堩御」「誱逝」
  - 嗜び（H）: 「す「「すを」「素晴ら」「嬉しい」「おぐでとう」
  - 怒り（A）: 「許せない」「怒り」「憤り」

### 5. 2コマページ比覇
- **現状**: テンプレ1（全画面1コマ）が75〜87%を占もる傾向がある
- **改善方法**: generate_comicle_csv.pyのセリフ結合条件を緩和する
  - デフォルト: 15字以下から棛続、または同一キャラ20字以下連続
  - 推奨: 20字以下かつ連続、または同一キャラ25字以下連続

### 6. フガリー付与瞇
- **目標**: 全セリフ行の40%以上にフガリーが付与されている状態
- **確認**: add_furigana.pyの出力ログで「変更件数」を確認する

## CSV形式の顸目对応表

generate_comicle_csv.pyはscript.csvの以下のカラムを期待する：

| generate_comicle_csv.py が期待するカラム | script.csvの実際のカラム |
|-----------------------------------------|-------------------------|
| `type` | `Type` |
| `character` | `Speaker` |
| `text` | `Content` |

カラム名が異なる場合は、以下のコマンドで変換する：

```python
import csv

rows = []
with open('script.csv', 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        rows.append({
            'type': row['Type'],
            'character': row['Speaker'],
            'text': row['Content']
        })

with open('script_converted.csv', 'w', encoding='utf-8', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=['type', 'character', 'text'])
    writer.writeheader()
    writer.writerows(rows)
```
