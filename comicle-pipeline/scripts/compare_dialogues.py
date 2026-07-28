#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
script.csv と comicle_output.csv のセリフ部分を比較分析する

Usage:
    python3 compare_dialogues.py <script.csv> <comicle_output.csv>
"""
import csv
import re
import sys
from collections import Counter


def remove_furigana(text):
    return re.sub(r'[（(][^）)]*[）)]', '', text)


def main():
    if len(sys.argv) != 3:
        print("Usage: python3 compare_dialogues.py <script.csv> <comicle_output.csv>")
        sys.exit(1)

    script_file = sys.argv[1]
    comicle_file = sys.argv[2]

    # ===== script.csv 読み込み =====
    script_rows = list(csv.DictReader(open(script_file, encoding='utf-8')))
    script_dialogues = [r for r in script_rows if r['Type'] == 'dialogue']
    script_pauses = [r for r in script_rows if r['Type'] == 'pause']

    print("=" * 60)
    print("【A】script.csv 基本情報")
    print("=" * 60)
    print(f"総行数: {len(script_rows)}")
    print(f"セリフ行数: {len(script_dialogues)}")
    print(f"ポーズ行数: {len(script_pauses)}")

    speaker_count = Counter(r['Speaker'] for r in script_dialogues)
    print(f"\n話者別セリフ数:")
    for speaker, count in sorted(speaker_count.items()):
        texts = [r['Content'] for r in script_dialogues if r['Speaker'] == speaker]
        total_chars = sum(len(remove_furigana(t)) for t in texts)
        print(f"  {speaker}: {count}行 / {total_chars}字（フリガナ除去後）")

    lengths = [len(remove_furigana(r['Content'])) for r in script_dialogues]
    print(f"\nセリフ文字数（フリガナ除去後）:")
    print(f"  最小: {min(lengths)}字 / 最大: {max(lengths)}字 / 平均: {sum(lengths)/len(lengths):.1f}字")
    print(f"  10字以下: {sum(1 for l in lengths if l <= 10)}件")
    print(f"  11-20字: {sum(1 for l in lengths if 11 <= l <= 20)}件")
    print(f"  21-30字: {sum(1 for l in lengths if 21 <= l <= 30)}件")
    print(f"  31字以上: {sum(1 for l in lengths if l > 30)}件")
    for r in script_dialogues:
        ln = len(remove_furigana(r['Content']))
        if ln > 30:
            print(f"    No.{r['No']} ({ln}字): {remove_furigana(r['Content'])}")

    furigana_pattern = re.compile(r'（[ァ-ンー]+）')
    script_with_furigana = [r for r in script_dialogues if furigana_pattern.search(r['Content'])]
    total_furigana = sum(len(furigana_pattern.findall(r['Content'])) for r in script_dialogues)
    print(f"\nフリガナ統計:")
    print(f"  フリガナ付きセリフ行: {len(script_with_furigana)}行 / {len(script_dialogues)}行")
    print(f"  フリガナ総数: {total_furigana}件")

    # ===== comicle_output.csv 読み込み =====
    comicle_rows = list(csv.DictReader(open(comicle_file, encoding='utf-8')))

    print("\n" + "=" * 60)
    print("【B】comicle_output.csv 基本情報")
    print("=" * 60)
    print(f"総ページ数: {len(comicle_rows)}")

    templates = Counter(r.get('使用するコマ割りテンプレ', '') for r in comicle_rows)
    print(f"\nテンプレート分布:")
    for k, v in sorted(templates.items()):
        print(f"  {k}: {v}ページ ({v/len(comicle_rows)*100:.1f}%)")

    # ストーリー欄からセリフを抽出
    comicle_dialogues = []
    for i, row in enumerate(comicle_rows):
        story = row.get('漫画作成のプロンプト', row.get('ストーリー', ''))
        matches = re.findall(r'(\d)\|([^|]+)\|([A-Z])\|([^\n]+)', story)
        for m in matches:
            comicle_dialogues.append({
                'page': i + 1,
                'panel': m[0],
                'character': m[1].strip(),
                'emotion': m[2],
                'text': m[3].strip()
            })

    print(f"\nセリフ抽出数（ストーリー欄）: {len(comicle_dialogues)}件")

    emotion_count = Counter(d['emotion'] for d in comicle_dialogues)
    print(f"\n感情コード分布:")
    for k, v in sorted(emotion_count.items()):
        print(f"  {k}: {v}件 ({v/max(len(comicle_dialogues),1)*100:.1f}%)")

    char_count = Counter(d['character'] for d in comicle_dialogues)
    print(f"\nキャラ別セリフ数（comicle）:")
    for k, v in sorted(char_count.items()):
        print(f"  {k}: {v}件")

    comicle_lengths = [len(remove_furigana(d['text'])) for d in comicle_dialogues]
    if comicle_lengths:
        print(f"\nセリフ文字数（フリガナ除去後）:")
        print(f"  最小: {min(comicle_lengths)}字 / 最大: {max(comicle_lengths)}字 / 平均: {sum(comicle_lengths)/len(comicle_lengths):.1f}字")
        print(f"  31字以上: {sum(1 for l in comicle_lengths if l > 30)}件")
        for d in comicle_dialogues:
            if len(remove_furigana(d['text'])) > 30:
                print(f"    P.{d['page']} ({len(remove_furigana(d['text']))}字): {remove_furigana(d['text'])}")

    # ===== セリフ対応比較 =====
    print("\n" + "=" * 60)
    print("【C】セリフ対応比較")
    print("=" * 60)

    script_texts = [remove_furigana(r['Content']) for r in script_dialogues]
    comicle_texts = [remove_furigana(d['text']) for d in comicle_dialogues]

    print(f"script セリフ数: {len(script_texts)}")
    print(f"comicle セリフ数: {len(comicle_texts)}")
    print(f"差異: {len(comicle_texts) - len(script_texts)}")

    # 全scriptセリフがcomicleに含まれているか確認
    all_prompts_clean = remove_furigana(' '.join(row.get('漫画作成のプロンプト', row.get('ストーリー', '')) for row in comicle_rows))
    found = sum(1 for t in script_texts if t in all_prompts_clean)
    print(f"\nscriptセリフのcomicle反映状況: {found}/{len(script_texts)}件")
    not_found = [t for t in script_texts if t not in all_prompts_clean]
    if not_found:
        print(f"未反映セリフ（{len(not_found)}件）:")
        for t in not_found[:10]:
            print(f"  「{t}」")

    # ===== 総合サマリー =====
    print("\n" + "=" * 60)
    print("【D】総合サマリー")
    print("=" * 60)
    print(f"script セリフ行数:         {len(script_dialogues)}")
    print(f"comicle セリフ抽出数:      {len(comicle_dialogues)}")
    print(f"セリフ反映率:              {found}/{len(script_texts)} ({found/max(len(script_texts),1)*100:.1f}%)")
    print(f"テンプレ1（1コマ）:        {templates.get('テンプレ1', 0)}ページ ({templates.get('テンプレ1', 0)/len(comicle_rows)*100:.1f}%)")
    multi = sum(v for k, v in templates.items() if k != 'テンプレ1')
    print(f"2コマページ合計:           {multi}ページ ({multi/len(comicle_rows)*100:.1f}%)")
    print(f"感情コードN（通常）率:     {emotion_count.get('N', 0)}/{len(comicle_dialogues)} ({emotion_count.get('N', 0)/max(len(comicle_dialogues),1)*100:.1f}%)")
    print(f"フリガナ除去後30字超え:    {sum(1 for l in comicle_lengths if l > 30)}件（script側）: {sum(1 for l in lengths if l > 30)}件")


if __name__ == '__main__':
    main()
