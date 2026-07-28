#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GPT-4.1-miniを使ってscript.csvのセリフ行にフリガナを追加する

フリガナ付与ルール:
  1. 小学生が読めない漢字（人名・官職・地名・特殊読みを含む）にカタカナフリガナを追加
  2. 年号・年月日には必ずフリガナを追加
  3. すでにフリガナが付いている箇所は変更しない
  4. フリガナは（カタカナ）形式

Usage:
    python3 add_furigana.py <input_script.csv> <output_script_furigana.csv>
"""

import csv
import json
import os
import sys
from openai import OpenAI

client = OpenAI()

def process_batch(batch):
    """バッチ処理でフリガナを追加"""
    input_data = [{"no": r['No'], "text": r['Content']} for r in batch]

    system_prompt = """あなたは日本語の教育コンテンツ専門の編集者です。
以下のルールに従い、与えられたセリフ行にフリガナを追加してください。

【フリガナ付与ルール】
1. 小学生（小学6年生まで）が読み間違える可能性のある漢字にフリガナを振る
   - 人名: 例）藤原道長 → 藤原道長（フジワラノミチナガ）
   - 官職名: 例）摂政 → 摂政（セッショウ）
   - 地名: 例）大宰府 → 大宰府（ダザイフ）
   - 特殊な読み: 例）崩御 → 崩御（ホウギョ）
2. 年号・年・月日には必ずフリガナを振る
   - 年号名: 例）康保 → 康保（コウホ）
   - 西暦年: 例）966年 → 966（キュウヒャクロワヸュウロワ）年
   - 月日: 例）10月16日 → 10月16日（ジュウガツジュウロワニチ）
3. すでにフリガナ（カタカナ括弧）が付いている箇所は変更しない
4. フリガナは（カタカナ）形式で漢字の直後に付ける
5. 常用漢字で小学生でも読める漢字（山、川、人、国など）にはフリガナ不要
6. ひらがなのみの語にはフリガナ不要

【出力形式】
入力と同じJSON配列形式で返す。変更がない行もすべて含める。
変更した行には "changed": true を付ける。"""

    user_prompt = f"""以下のセリフ行にフリガナを追加してください。

入力:
{json.dumps(input_data, ensure_ascii=False, indent=2)}

出力形式（JSON配列）:
[
  {{"no": "1", "text": "修正後のテキスト", "changed": false}},
  {{"no": "2", "text": "修正後のテキスト", "changed": true}},
  ...
]

すべての行を出力してください（変更なしの行も含む）。"""

    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.1,
        response_format={"type": "json_object"}
    )

    result_text = response.choices[0].message.content
    result = json.loads(result_text)

    if isinstance(result, dict):
        for key in result:
            if isinstance(result[key], list):
                result = result[key]
                break

    result = [r for r in result if isinstance(r, dict)]
    return result


def hira_to_kata(text):
    """ひらがなをカタカナに変換"""
    result = []
    for ch in text:
        code = ord(ch)
        if 0x3041 <= code <= 0x3096:
            result.append(chr(code + 0x60))
        else:
            result.append(ch)
    return ''.join(result)


def fix_hira_furigana(text):
    """括弧内のひらがなフリガナをカタカナに変換"""
    import re
    def replace_match(m):
        inner = m.group(1)
        if re.fullmatch(r'[ぁ-んー・ノ]+', inner):
            return '（' + hira_to_kata(inner) + '）'
        return m.group(0)
    return re.sub(r'（([^）]+)）', replace_match, text)


def main():
    if len(sys.argv) != 3:
        print("Usage: python3 add_furigana.py <input_script.csv> <output_script_furigana.csv>")
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

    BATCH_SIZE = 20
    corrected_map = {}

    all_results = []
    for i in range(0, len(dialogue_rows), BATCH_SIZE):
        batch = dialogue_rows[i:i+BATCH_SIZE]
        print(f"Processing batch {i//BATCH_SIZE + 1}/{(len(dialogue_rows)-1)//BATCH_SIZE + 1} ...")
        results = process_batch(batch)
        all_results.extend(results)
        print(f"  → {sum(1 for r in results if r.get('changed', False))} rows changed")

    for r in all_results:
        corrected_map[str(r['no'])] = r

    changed_rows = [r for r in all_results if r.get('changed', False)]
    print(f"\n=== フリガナ追加: {len(changed_rows)}件 ===")
    for r in changed_rows:
        orig = next((row['Content'] for row in dialogue_rows if row['No'] == r['no']), '')
        print(f"  No.{r['no']}: 「{orig}」 → 「{r['text']}」")

    # ひらがなフリガナをカタカナに統一
    output_rows = []
    for row in script_rows:
        new_row = dict(row)
        if row['Type'] == 'dialogue' and row['No'] in corrected_map:
            text = corrected_map[row['No']]['text']
            new_row['Content'] = fix_hira_furigana(text)
        output_rows.append(new_row)

    with open(output_file, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(output_rows)

    print(f"\n✅ フリガナ付きCSVを保存しました: {output_file}")


if __name__ == '__main__':
    main()
