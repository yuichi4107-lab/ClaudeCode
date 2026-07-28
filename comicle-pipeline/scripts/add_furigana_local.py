#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
add_furigana_local.py
OPENAI_API_KEY不要のルールベース版フリガナ付与スクリプト。
add_furigana.pyと同一のCSV入出力フォーマットを維持する。

フリガナ付与ルール:
  1. 小学生が読めない漢字（人名・官職・地名・特殊読み）
  2. 年号・年月日には必ずフリガナを付与
  3. すでにフリガナが付いている箇所は変更しない
  4. フリガナは（カタカナ）形式
"""
import csv
import re
import sys

# フリガナ辞書（長いキーから順に処理するためリストで定義）
FURIGANA_RULES = [
    # 人名（長い方から）
    ("後白河天皇", "後白河天皇（ゴシラカワテンノウ）"),
    ("後白河法皇", "後白河法皇（ゴシラカワホウオウ）"),
    ("崇徳上皇", "崇徳上皇（ストクジョウコウ）"),
    ("高倉天皇", "高倉天皇（タカクラテンノウ）"),
    ("安徳天皇", "安徳天皇（アントクテンノウ）"),
    ("平清盛", "平清盛（タイラノキヨモリ）"),
    ("平忠盛", "平忠盛（タイラノタダモリ）"),
    ("平時忠", "平時忠（タイラノトキタダ）"),
    ("源義朝", "源義朝（ミナモトノヨシトモ）"),
    ("源頼朝", "源頼朝（ミナモトノヨリトモ）"),
    ("池禅尼", "池禅尼（イケノゼンニ）"),
    ("清盛", "清盛（キヨモリ）"),
    ("忠盛", "忠盛（タダモリ）"),
    ("義朝", "義朝（ヨシトモ）"),
    ("頼朝", "頼朝（ヨリトモ）"),
    ("徳子", "徳子（トクコ）"),
    # 官職・制度
    ("太政大臣", "太政大臣（ダジョウダイジン）"),
    ("院政", "院政（インセイ）"),
    # 歴史用語
    ("保元の乱", "保元（ホウゲン）の乱（ラン）"),
    ("平治の乱", "平治（ヘイジ）の乱（ラン）"),
    ("鹿ケ谷の陰謀", "鹿ケ谷（シシガタニ）の陰謀（インボウ）"),
    ("治承三年の政変", "治承（ジショウ）三年の政変（セイヘン）"),
    ("壇ノ浦の戦い", "壇ノ浦（ダンノウラ）の戦（タタカ）い"),
    ("日宋貿易", "日宋貿易（ニッソウボウエキ）"),
    ("平家物語", "平家物語（ヘイケモノガタリ）"),
    ("鎌倉幕府", "鎌倉幕府（カマクラバクフ）"),
    # 地名
    ("瀬戸内海", "瀬戸内海（セトナイカイ）"),
    ("福原", "福原（フクハラ）"),
    ("伊豆", "伊豆（イズ）"),
    # その他
    ("藤原氏", "藤原氏（フジワラシ）"),
    ("宋銭", "宋銭（ソウセン）"),
    ("通貨経済", "通貨経済（ツウカケイザイ）"),
    ("挙兵", "挙兵（キョヘイ）"),
    ("幽閉", "幽閉（ユウヘイ）"),
    ("熱病", "熱病（ネツビョウ）"),
    ("滅亡", "滅亡（メツボウ）"),
    ("嘆願", "嘆願（タンガン）"),
    ("敗死", "敗死（ハイシ）"),
    ("処罰", "処罰（ショバツ）"),
    ("即位", "即位（ソクイ）"),
    ("就任", "就任（シュウニン）"),
    ("側近", "側近（ソッキン）"),
    ("継母", "継母（ママハハ）"),
    ("助命", "助命（ジョメイ）"),
    ("求心力", "求心力（キュウシンリョク）"),
    ("莫大", "莫大（バクダイ）"),
    ("先見の明", "先見（センケン）の明（メイ）"),
]

# 年号パターン
YEAR_RULES = [
    (r'(?<!\d)1118年', '1118（センヒャクジュウハチ）年'),
    (r'(?<!\d)1156年', '1156（センヒャクゴジュウロク）年'),
    (r'(?<!\d)1159年', '1159（センヒャクゴジュウク）年'),
    (r'(?<!\d)1167年', '1167（センヒャクロクジュウナナ）年'),
    (r'(?<!\d)1177年', '1177（センヒャクナナジュウナナ）年'),
    (r'(?<!\d)1179年', '1179（センヒャクナナジュウク）年'),
    (r'(?<!\d)1180年', '1180（センヒャクハチジュウ）年'),
    (r'(?<!\d)1181年', '1181（センヒャクハチジュウイチ）年'),
    (r'(?<!\d)64歳', '64（ロクジュウヨン）歳（サイ）'),
    (r'(?<!\d)50歳', '50（ゴジュッ）歳（サイ）'),
    (r'(?<!\d)3年後', '3（サン）年後（ネンゴ）'),
    (r'(?<!\d)4年', '4（ヨン）年'),
]


def apply_furigana(text):
    """セリフにフリガナを付与する"""
    if not text:
        return text, False

    original = text
    result = text

    # 年号パターンを先に適用
    for pattern, replacement in YEAR_RULES:
        # 既にフリガナがあるか確認
        match = re.search(pattern, result)
        if match:
            start = match.start()
            after = result[match.end():]
            if not after.startswith('（'):
                result = result[:start] + re.sub(pattern, replacement, result[start:], count=1)

    # 辞書ベースのフリガナ付与
    for key, value in FURIGANA_RULES:
        if key not in result:
            continue
        # 既にフリガナ付きの形が含まれていないか確認
        if value in result:
            continue
        # キーの直後に（がある場合はスキップ（既にフリガナ済み）
        pos = 0
        while True:
            idx = result.find(key, pos)
            if idx == -1:
                break
            after_pos = idx + len(key)
            if after_pos < len(result) and result[after_pos] == '（':
                pos = after_pos
                continue
            # 置換（最初の1箇所のみ）
            result = result[:idx] + value + result[after_pos:]
            break

    changed = result != original
    return result, changed


def main():
    if len(sys.argv) != 3:
        print("Usage: python3 add_furigana_local.py <input_script.csv> <output_script_furigana.csv>")
        sys.exit(1)

    input_file = sys.argv[1]
    output_file = sys.argv[2]

    script_rows = []
    with open(input_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        for row in reader:
            script_rows.append(dict(row))

    dialogue_rows = [r for r in script_rows if r['Type'] == 'dialogue']
    print(f"Total dialogue rows: {len(dialogue_rows)}")

    changed_count = 0
    furigana_total = 0
    changed_examples = []

    for row in script_rows:
        if row['Type'] == 'dialogue' and row['Content']:
            original = row['Content']
            new_text, changed = apply_furigana(original)
            if changed:
                changed_count += 1
                changed_examples.append((row['No'], original, new_text))
            row['Content'] = new_text
            furigana_total += len(re.findall(r'（[ァ-ヶー]+）', new_text))

    with open(output_file, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(script_rows)

    print(f"\n=== フリガナ追加: {changed_count}件 ===")
    for no, orig, new in changed_examples[:10]:
        print(f"  No.{no}: 「{orig}」 → 「{new}」")
    if len(changed_examples) > 10:
        print(f"  ... 他{len(changed_examples) - 10}件")

    furigana_lines = sum(1 for r in script_rows if r['Type'] == 'dialogue' and re.search(r'（[ァ-ヶー]+）', r['Content']))
    print(f"\nフリガナ統計:")
    print(f"  フリガナ付きセリフ行: {furigana_lines}行 / {len(dialogue_rows)}行")
    print(f"  フリガナ総数: {furigana_total}件")
    print(f"\n✅ フリガナ付きCSVを保存しました: {output_file}")
    print(f"  方式: ルールベース辞書（OPENAI_API_KEY未設定のため）")


if __name__ == '__main__':
    main()
