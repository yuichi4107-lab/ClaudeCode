#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Comicle CSV Generator
台本CSVからコミクル用CSVを生成するスクリプト

Usage:
    python generate_comicle_csv.py <input_script.csv> <output_comicle.csv> <target_pages> [--character-defs <char_defs.json>]

Arguments:
    input_script.csv: 入力台本CSVファイル（type, character, textカラムを含む）
    output_comicle.csv: 出力コミクル用CSVファイル
    target_pages: 目標ページ数（例: 120）
    --character-defs: キャラクター定義JSONファイル（オプション）
"""

import csv
import re
import sys
import json
import argparse

def remove_furigana(text):
    """セリフ内の（）で囲まれた読み仮名を削除"""
    return re.sub(r'[（(][^）)]*[）)]', '', text)

def estimate_emotion(text, character):
    """セリフの内容から感情コードを推定"""
    text_clean = remove_furigana(text)

    if any(word in text_clean for word in ['！！', 'ガハハ', 'すごい', 'わぁ', 'ええっ', '面白そう']):
        return 'H'
    elif any(word in text_clean for word in ['ひどい', '切ない', '悲し', 'なんだか', '敗れ', 'つらい', 'ひとりぼっち']):
        return 'S'
    elif any(word in text_clean for word in ['？', 'ですか', 'でしょう', 'どう']):
        return 'N'
    else:
        return 'N'

def select_action(character, emotion, text, index):
    """キャラクターと感情からアクション描写を生成（セリフ内容を含めない）"""
    text_clean = remove_furigana(text)

    # ミユ（質問役・女子大生）のアクションパターン
    miyu_actions = {
        'N': [
            '顎に手を当てて考え込んでいる',
            '教授の方を向いて真剣に聞いている',
            'メモを取りながら頷いている',
            '資料に目を落としている',
            '腕を組んで考え込んでいる',
            '興味深そうに身を乗り出している',
        ],
        'H': [
            '目を輝かせて身を乗り出している',
            '両手を合わせて驚いている',
            '嬉しそうに笑顔を見せている',
            '勢いよく立ち上がっている',
        ],
        'S': [
            '眉を寄せて悲しそうな表情をしている',
            '胸に手を当てて感情を込めている',
            '目を伏せて沈んだ表情をしている',
            '唇を噛んで切なそうにしている',
        ],
    }

    # ヨウイチ（教授・解説役）のアクションパターン
    youichi_actions = {
        'N': [
            '腕を組んで落ち着いた表情で語っている',
            '人差し指を立てて説明している',
            '資料を広げながら丁寧に解説している',
            '真剣な表情で歴史を振り返っている',
            '穏やかな表情で語りかけている',
            '顎に手を添えて思案顔をしている',
        ],
        'H': [
            '力強い表情で熱く語っている',
            '身振りを交えて生き生きと話している',
            '目を見開いて強調している',
            '拳を握って力説している',
        ],
        'S': [
            '目を細めて遠くを見つめている',
            '静かに首を振りながら語っている',
            '重い表情で歴史の悲劇を語っている',
            '沈痛な面持ちで振り返っている',
        ],
    }

    if character == 'ミユ':
        actions = miyu_actions.get(emotion, miyu_actions['N'])
    elif character == 'ヨウイチ':
        actions = youichi_actions.get(emotion, youichi_actions['N'])
    else:
        actions = [f'{character}が話している']

    return actions[index % len(actions)]

def select_background(text, index, total, background_config=None):
    """セリフの内容に応じて背景を選択"""
    text_clean = remove_furigana(text)

    default_historical_backgrounds = [
        '平安時代の京都の街並み、貴族の邸宅が見える',
        '関東の荒れた大地、農民が逃げ出す様子',
        '朝廷の宮殿、豪華な装飾と貴族たち',
        '戦場の風景、武士たちが戦う様子',
        '古い国府の建物、役人が集まる',
        '平安時代の農村、田畑が広がる',
        '京都の御所、天皇の権威を示す建物',
        '関東の武士の館、質実剛健な雰囲気',
        '平安時代の巻物や文献が広けられている',
        '戦いの後の荒野、敗者の姿',
        '平安時代の戦場、矢が飛び交う',
        '将門の首が晒される京都の街',
        '関東平野に立つ武士たちの姿',
        '朝廷の役人たちが集まる会議の場',
        '平安時代の地方の役所、腐敗した役人'
    ]

    default_modern_backgrounds = [
        '大学の研究室、本棚と机が見える歴史的な雰囲気',
        '古い日本の巻物や歴史書が並ぶ本棚',
        '研究室の窓から差し込む柔らかい光',
        '歴史書が積まれた机、古い文献が見える',
        '歴史の手が開かれるイメージ、光が差し込む'
    ]

    if background_config:
        historical_keywords = background_config.get('historical_keywords', [])
        historical_backgrounds = background_config.get('historical_backgrounds', default_historical_backgrounds)
        modern_backgrounds = background_config.get('modern_backgrounds', default_modern_backgrounds)
    else:
        historical_keywords = ['将門', '朝廷', '天皇', '律令', '国司', '京都', '関東', '戦', '皇族',
                              '平安', '貴族', '農民', '土地', '国府', '新皇', '武士', '討伐', '貞盛', '藤太']
        historical_backgrounds = default_historical_backgrounds
        modern_backgrounds = default_modern_backgrounds

    if any(keyword in text_clean for keyword in historical_keywords):
        return historical_backgrounds[index % len(historical_backgrounds)]
    else:
        return modern_backgrounds[index % len(modern_backgrounds)]

def select_onomatopoeia(text, character, emotion):
    """セリフの内容と感情から適切なオノマトペを選択"""
    text_clean = remove_furigana(text)

    if '！！' in text or '！' in text:
        return 'バーン'
    elif '？' in text:
        return 'キョトン'
    elif 'ガハハ' in text_clean:
        return 'ガハハ'
    elif '驚' in text_clean or 'ええっ' in text_clean:
        return 'ビクッ'
    elif '笑' in text_clean or '面白' in text_clean:
        return 'ニコッ'
    elif '悲し' in text_clean or '切ない' in text_clean:
        return 'シーン'
    elif '戦' in text_clean or '討' in text_clean:
        return 'ザッ'
    else:
        default_onomatopoeia = ['スッ', 'フッ', 'サッ', 'パッ', 'ジーッ']
        return default_onomatopoeia[len(text_clean) % len(default_onomatopoeia)]

def get_fukidashi(emotion):
    """感情コードから吹き出しタイプを返す"""
    if emotion == 'H':
        return '[強調の吹き出し]'
    elif emotion == 'S':
        return '[震える吹き出し]'
    else:
        return '[通常の吹き出し]'

def should_combine_with_next(current, next_dialogue, index, total):
    """次のセリフと組み合わせるべきか判定"""
    current_text = remove_furigana(current['text'])
    next_text = remove_furigana(next_dialogue['text'])

    # 重要シーンは単独ページにする
    important_keywords = [
        '新皇', '討ち死に', '晒し首', '結末', '敗れ去った',
        '立ち上がり', '反逆者', '挑戦状', '翻弄された敗者',
        '引き裂かれて', '武士の時代', '教授！'
    ]

    if any(keyword in current_text for keyword in important_keywords):
        return False
    if any(keyword in next_text for keyword in important_keywords):
        return False

    # 異なるキャラの掛け合い（短めのセリフ同士）は結合しやすい
    if current['character'] != next_dialogue['character']:
        if len(current_text) <= 30 and len(next_text) <= 30:
            return True

    # 同じキャラの連続セリフも結合
    if current['character'] == next_dialogue['character']:
        if len(current_text) <= 25 and len(next_text) <= 25:
            return True

    # 長いセリフ同士でも片方が短ければ結合
    if len(current_text) <= 15 or len(next_text) <= 15:
        return True

    # それ以外でも両方50字以内なら結合可能
    if len(current_text) <= 50 and len(next_text) <= 50:
        return True

    return False

def generate_comicle_csv(input_csv, output_csv, target_pages, character_defs=None, background_config=None):
    """台本CSVからコミクル用CSVを生成"""
    with open(input_csv, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        script_data = list(reader)

    dialogues = [row for row in script_data if row['type'] == 'dialogue']

    default_char_defs = {
        'ミユ': 'ミユ: 添付のミユ.pngと同一。金髪ボブヘア、白Tシャツの上にベージュのケーブルニットカーディガン、紺デニムパンツ、白スニーカー、ネックレス。服装は全ページ共通で絶対に変えない',
        'ヨウイチ': 'ヨウイチ: 添付のヨウイチ.pngと同一。黒髪短髪、チャコールグレーのスーツ（ジャケット＋スラックス）、白シャツ（ノーネクタイ）、茶色の革靴。眼鏡をかけない。服装は全ページ共通で絶対に変えない'
    }

    if character_defs is None:
        character_defs = default_char_defs

    total_dialogues = len(dialogues)
    target_combines = total_dialogues - target_pages

    if target_combines < 0:
        target_combines = 0
        print(f"Warning: Cannot reach {target_pages} pages with {total_dialogues} dialogues. Will create {total_dialogues} pages instead.")

    pages = []
    page_num = 1
    i = 0
    combine_count = 0
    all_characters = list(character_defs.keys())

    while i < len(dialogues):
        current = dialogues[i]
        character = current['character']
        text = current['text']
        text_clean = remove_furigana(text)
        emotion = estimate_emotion(text, character)

        has_next = i + 1 < len(dialogues)

        should_combine = False
        if has_next and combine_count < target_combines:
            next_dialogue = dialogues[i + 1]
            should_combine = should_combine_with_next(current, next_dialogue, i, len(dialogues))

        # 相手キャラを特定
        other_character = all_characters[1] if character == all_characters[0] else all_characters[0]

        if should_combine:
            next_dialogue = dialogues[i + 1]
            next_character = next_dialogue['character']
            next_text = next_dialogue['text']
            next_text_clean = remove_furigana(next_text)
            next_emotion = estimate_emotion(next_text, next_character)
            next_other = all_characters[1] if next_character == all_characters[0] else all_characters[0]

            # 2コマページ: 両キャラを定義
            if character == next_character:
                char_def = character_defs.get(character, f'{character}: キャラクター定義なし')
            else:
                char_def = f'{character_defs.get(character, f"{character}: キャラクター定義なし")}, {character_defs.get(next_character, f"{next_character}: キャラクター定義なし")}'

            background1 = select_background(text, i, len(dialogues), background_config)
            background2 = select_background(next_text, i+1, len(dialogues), background_config)
            onomatopoeia1 = select_onomatopoeia(text, character, emotion)
            onomatopoeia2 = select_onomatopoeia(next_text, next_character, next_emotion)
            action1 = select_action(character, emotion, text, i)
            action2 = select_action(next_character, next_emotion, next_text, i+1)
            fukidashi1 = get_fukidashi(emotion)
            fukidashi2 = get_fukidashi(next_emotion)

            if page_num % 5 == 0:
                template = 'テンプレ4'
                koma_config = f'テンプレ4: 右側は{character}の表情のアップ、左側は{next_character}のリアクション。'
            elif page_num % 3 == 0:
                template = 'テンプレ5'
                koma_config = f'テンプレ5: 上段で{character}が語り、下段で{next_character}が反応する構図。'
            else:
                template = 'テンプレ2'
                koma_config = f'テンプレ2: 右側は{character}のアップ、左側は{next_character}の反応。'

            story = f"""1コマ目 (右): {character}が{action1}。オノマトペ「{onomatopoeia1}」。背景は{background1}。 + {character}「{text_clean}」 {fukidashi1}
2コマ目 (左): {next_character}が{action2}。オノマトペ「{onomatopoeia2}」。背景は{background2}。 + {next_character}「{next_text_clean}」 {fukidashi2}"""

            serifu_section = f"1|{character}|{emotion}|{text_clean}\n2|{next_character}|{next_emotion}|{next_text_clean}"

            i += 2
            combine_count += 1

        else:
            # 1コマページ: 話者のみ定義
            char_def = character_defs.get(character, f'{character}: キャラクター定義なし')

            background = select_background(text, i, len(dialogues), background_config)
            onomatopoeia = select_onomatopoeia(text, character, emotion)
            action = select_action(character, emotion, text, i)
            fukidashi = get_fukidashi(emotion)

            template = 'テンプレ1'
            koma_config = f'テンプレ1: 全画面で{character}が{action[:10]}構図。'
            story = f"1コマ目 (全体): {character}が{action}。オノマトペ「{onomatopoeia}」。背景は{background}。 + {character}「{text_clean}」 {fukidashi}"
            serifu_section = f"1|{character}|{emotion}|{text_clean}"

            i += 1

        prompt = f"""◆【絶対最優先】キャラクター外見: {char_def}
◆【出力サイズ】--ar 16:9
◆【コマ構成】{koma_config}
◆【作画】ビジネス漫画向け、清潔感重視、整った線画、現代的でクリアなアニメ調、フルカラー
◆【ストーリー】
{story}
{serifu_section}"""

        pages.append({
            'page_num': page_num,
            'template': template,
            'prompt': prompt
        })

        page_num += 1

    with open(output_csv, 'w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['ページ番号', '使用するコマ割りテンプレ', '漫画作成のプロンプト'])

        for page in pages:
            writer.writerow([page['page_num'], page['template'], page['prompt']])

    print(f'CSV file generated: {output_csv}')
    print(f'Total pages: {len(pages)}')
    print(f'Dialogues processed: {i} / {len(dialogues)}')
    print(f'2-panel pages: {combine_count}')
    print(f'1-panel pages: {len(pages) - combine_count}')

def main():
    parser = argparse.ArgumentParser(description='台本CSVからコミクル用CSVを生成')
    parser.add_argument('input_csv', help='入力台本CSVファイル')
    parser.add_argument('output_csv', help='出力コミクル用CSVファイル')
    parser.add_argument('target_pages', type=int, help='目標ページ数')
    parser.add_argument('--character-defs', help='キャラクター定義JSONファイル（オプション）')
    parser.add_argument('--background-config', help='背景設定JSONファイル（オプション）')

    args = parser.parse_args()

    character_defs = None
    if args.character_defs:
        with open(args.character_defs, 'r', encoding='utf-8') as f:
            character_defs = json.load(f)

    background_config = None
    if args.background_config:
        with open(args.background_config, 'r', encoding='utf-8') as f:
            background_config = json.load(f)

    generate_comicle_csv(args.input_csv, args.output_csv, args.target_pages, character_defs, background_config)

if __name__ == '__main__':
    main()
